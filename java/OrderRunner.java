import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.io.Writer;
import java.lang.annotation.Annotation;
import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Collection;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.TreeMap;

/**
 * Runs a list of JUnit test methods in the given order inside ONE JVM, so static state
 * written by an earlier test is visible to later tests (this is what makes an
 * order-dependent victim fail after its polluter).
 *
 * Compiled with no JUnit dependency: JUnit 4/3 and JUnit 5 (Jupiter) are driven by
 * reflection, so the same class works with whatever JUnit version the project uses.
 *
 * Usage:
 *   java -cp <runner-dir + project test classpath> OrderRunner run  out.json  pkg.Cls#m1 pkg.Cls#m2 ...
 *   java -cp <...> OrderRunner list out.txt  <test-classes-dir>
 *   java -cp <...> OrderRunner state out.json classes.txt [pkg.Cls#m ...]
 *
 * "state" (PolluTrace G2) runs the given tests (possibly none), then snapshots the static
 * fields of every class listed in classes.txt plus system properties, default locale and
 * time zone. Comparing the snapshot of a clean JVM with the snapshot after the polluter
 * shows exactly which shared state the polluter left behind.
 */
public class OrderRunner {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: OrderRunner run out.json Cls#m ... | list out.txt testClassesDir");
            System.exit(2);
        }
        if (args[0].equals("run")) {
            List<String> tests = new ArrayList<String>();
            for (int i = 2; i < args.length; i++) tests.add(args[i]);
            run(args[1], tests);
        } else if (args[0].equals("list")) {
            list(args[1], new File(args[2]));
        } else if (args[0].equals("state")) {
            List<String> tests = new ArrayList<String>();
            for (int i = 3; i < args.length; i++) tests.add(args[i]);
            state(args[1], args[2], tests);
        }
        System.exit(0); // do not wait for non-daemon threads left by tests
    }

    // ------------------------------------------------------------------ run
    static void run(String out, List<String> tests) throws Exception {
        Writer w = new OutputStreamWriter(new FileOutputStream(out), "UTF-8");
        w.write(runTests(tests).append('}').toString());
        w.close();
    }

    /** Runs the tests and returns the JSON object text without its closing brace. */
    static StringBuilder runTests(List<String> tests) {
        StringBuilder sb = new StringBuilder("{\"results\":[");
        for (int i = 0; i < tests.size(); i++) {
            String t = tests.get(i);
            long t0 = System.currentTimeMillis();
            String status;
            String trace = "";
            try {
                int hash = t.lastIndexOf('#');
                String cls = t.substring(0, hash), m = t.substring(hash + 1);
                Class<?> c = Class.forName(cls, false, OrderRunner.class.getClassLoader());
                String[] r = isJupiter(c, m) ? runJupiter(c, m) : runJUnit4(c, m);
                status = r[0];
                trace = r[1];
            } catch (Throwable e) {
                status = "ERROR";
                trace = stack(e);
            }
            long ms = System.currentTimeMillis() - t0;
            if (i > 0) sb.append(',');
            sb.append("{\"test\":").append(q(t)).append(",\"status\":").append(q(status))
              .append(",\"ms\":").append(ms).append(",\"trace\":").append(q(cut(trace, 6000))).append('}');
        }
        sb.append(']');
        return sb;
    }

    // ---------------------------------------------------------------- state
    static final int MAX_REPR = 400, MAX_ELEMS = 8, MAX_DEPTH = 2;

    static void state(String out, String classesFile, List<String> tests) throws Exception {
        List<String> classes = new ArrayList<String>();
        BufferedReader br = new BufferedReader(new InputStreamReader(new FileInputStream(classesFile), "UTF-8"));
        for (String l; (l = br.readLine()) != null; ) if (l.trim().length() > 0) classes.add(l.trim());
        br.close();
        // initialise the classes first so a clean snapshot and a polluted one see the same set
        List<Class<?>> loaded = new ArrayList<Class<?>>();
        List<String> missing = new ArrayList<String>();
        for (String cn : classes) {
            try {
                loaded.add(Class.forName(cn, true, OrderRunner.class.getClassLoader()));
            } catch (Throwable e) {
                missing.add(cn);
            }
        }
        StringBuilder sb = runTests(tests);
        TreeMap<String, String> snap = new TreeMap<String, String>();
        for (Class<?> c : loaded) snapshot(c, snap);
        Properties props = System.getProperties();
        for (String k : props.stringPropertyNames()) snap.put("System.property:" + k, cut(props.getProperty(k), MAX_REPR));
        snap.put("Locale.default", String.valueOf(java.util.Locale.getDefault()));
        snap.put("TimeZone.default", java.util.TimeZone.getDefault().getID());
        sb.append(",\"state\":{");
        boolean first = true;
        for (Map.Entry<String, String> e : snap.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            sb.append(q(e.getKey())).append(':').append(q(e.getValue()));
        }
        sb.append("},\"missing\":[");
        for (int i = 0; i < missing.size(); i++) sb.append(i > 0 ? "," : "").append(q(missing.get(i)));
        sb.append("]}");
        Writer w = new OutputStreamWriter(new FileOutputStream(out), "UTF-8");
        w.write(sb.toString());
        w.close();
    }

    static void snapshot(Class<?> c, Map<String, String> snap) {
        Field[] fs;
        try {
            fs = c.getDeclaredFields();
        } catch (Throwable e) {
            return;
        }
        for (Field f : fs) {
            int mod = f.getModifiers();
            if (!Modifier.isStatic(mod) || f.isSynthetic()) continue;
            // compile-time constants cannot change
            if (Modifier.isFinal(mod) && (f.getType().isPrimitive() || f.getType() == String.class)) continue;
            String key = c.getName() + "." + f.getName();
            try {
                f.setAccessible(true);
                snap.put(key, cut(repr(f.get(null), 0, new IdentityHashMap<Object, Boolean>()), MAX_REPR));
            } catch (Throwable e) {
                snap.put(key, "<inaccessible: " + e.getClass().getSimpleName() + ">");
            }
        }
    }

    /** A JVM-independent description of a value (no identity hash codes). */
    static String repr(Object v, int depth, IdentityHashMap<Object, Boolean> seen) {
        if (v == null) return "null";
        Class<?> c = v.getClass();
        if (v instanceof String) return q((String) v);
        if (v instanceof Number || v instanceof Boolean || v instanceof Character || c.isEnum()) return String.valueOf(v);
        if (v instanceof Class) return "class " + ((Class<?>) v).getName();
        if (seen.containsKey(v)) return "<cycle>";
        seen.put(v, Boolean.TRUE);
        try {
            if (c.isArray()) {
                int n = Array.getLength(v);
                StringBuilder b = new StringBuilder(c.getComponentType().getSimpleName() + "[" + n + "]{");
                for (int i = 0; i < Math.min(n, MAX_ELEMS); i++) b.append(i > 0 ? "," : "").append(depth < MAX_DEPTH ? repr(Array.get(v, i), depth + 1, seen) : "..");
                return b.append(n > MAX_ELEMS ? ",..}" : "}").toString();
            }
            if (v instanceof Map) {
                Map<?, ?> m = (Map<?, ?>) v;
                StringBuilder b = new StringBuilder(c.getSimpleName() + "(size=" + m.size() + "){");
                int i = 0;
                for (Iterator<? extends Map.Entry<?, ?>> it = m.entrySet().iterator(); it.hasNext() && i < MAX_ELEMS; i++) {
                    Map.Entry<?, ?> e = it.next();
                    b.append(i > 0 ? "," : "").append(depth < MAX_DEPTH ? repr(e.getKey(), depth + 1, seen) + "=" + repr(e.getValue(), depth + 1, seen) : "..");
                }
                return b.append(m.size() > MAX_ELEMS ? ",..}" : "}").toString();
            }
            if (v instanceof Collection) {
                Collection<?> col = (Collection<?>) v;
                StringBuilder b = new StringBuilder(c.getSimpleName() + "(size=" + col.size() + "){");
                int i = 0;
                for (Iterator<?> it = col.iterator(); it.hasNext() && i < MAX_ELEMS; i++)
                    b.append(i > 0 ? "," : "").append(depth < MAX_DEPTH ? repr(it.next(), depth + 1, seen) : "..");
                return b.append(col.size() > MAX_ELEMS ? ",..}" : "}").toString();
            }
            if (v instanceof ThreadLocal) return "ThreadLocal{" + repr(((ThreadLocal<?>) v).get(), depth + 1, seen) + "}";
            if (v instanceof java.util.concurrent.atomic.AtomicInteger || v instanceof java.util.concurrent.atomic.AtomicLong
                || v instanceof java.util.concurrent.atomic.AtomicBoolean || v instanceof java.util.concurrent.atomic.AtomicReference)
                return c.getSimpleName() + "{" + v + "}";
            // other objects: their own instance fields, one level deep
            if (depth >= MAX_DEPTH) return c.getName();
            StringBuilder b = new StringBuilder(c.getName() + "{");
            int i = 0;
            for (Class<?> k = c; k != null && k != Object.class && i < MAX_ELEMS; k = k.getSuperclass()) {
                for (Field f : k.getDeclaredFields()) {
                    if (Modifier.isStatic(f.getModifiers()) || f.isSynthetic() || i >= MAX_ELEMS) continue;
                    try {
                        f.setAccessible(true);
                        b.append(i++ > 0 ? "," : "").append(f.getName()).append('=').append(repr(f.get(v), depth + 1, seen));
                    } catch (Throwable e) {
                        b.append(i++ > 0 ? "," : "").append(f.getName()).append("=?");
                    }
                }
            }
            return b.append('}').toString();
        } finally {
            seen.remove(v);
        }
    }

    static boolean isJupiter(Class<?> c, String m) {
        for (Class<?> k = c; k != null && k != Object.class; k = k.getSuperclass()) {
            for (Method meth : k.getDeclaredMethods()) {
                if (!meth.getName().equals(m)) continue;
                for (Annotation a : meth.getAnnotations()) {
                    String n = a.annotationType().getName();
                    if (n.startsWith("org.junit.jupiter")) return true;
                }
            }
        }
        return false;
    }

    /** JUnit 4 (also runs JUnit 3 TestCase classes). Returns {status, trace}. */
    static String[] runJUnit4(Class<?> c, String m) throws Exception {
        Class<?> reqC = Class.forName("org.junit.runner.Request");
        Object req = reqC.getMethod("method", Class.class, String.class).invoke(null, c, m);
        Class<?> coreC = Class.forName("org.junit.runner.JUnitCore");
        Object core = coreC.newInstance();
        Object res = coreC.getMethod("run", reqC).invoke(core, req);
        int runCount = (Integer) res.getClass().getMethod("getRunCount").invoke(res);
        int ignored = (Integer) res.getClass().getMethod("getIgnoreCount").invoke(res);
        List<?> fails = (List<?>) res.getClass().getMethod("getFailures").invoke(res);
        if (!fails.isEmpty()) {
            Object f = fails.get(0);
            String tr = (String) f.getClass().getMethod("getTrace").invoke(f);
            // "No tests found matching Method ..." is reported as a failure by JUnit 4
            if (tr != null && tr.contains("No tests found matching")) return new String[]{"NOT_FOUND", tr};
            return new String[]{"FAIL", tr};
        }
        if (runCount == 0) return new String[]{ignored > 0 ? "SKIPPED" : "NOT_FOUND", ""};
        return new String[]{"PASS", ""};
    }

    /** JUnit 5 Jupiter through the Platform Launcher. Returns {status, trace}. */
    static String[] runJupiter(Class<?> c, String m) throws Exception {
        Class<?> lf = Class.forName("org.junit.platform.launcher.core.LauncherFactory");
        Object launcher = lf.getMethod("create").invoke(null);
        Class<?> ds = Class.forName("org.junit.platform.engine.discovery.DiscoverySelectors");
        Object sel = ds.getMethod("selectMethod", Class.class, String.class).invoke(null, c, m);
        Class<?> selC = Class.forName("org.junit.platform.engine.DiscoverySelector");
        Object selArr = Array.newInstance(selC, 1);
        Array.set(selArr, 0, sel);
        Class<?> rb = Class.forName("org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder");
        Object b = rb.getMethod("request").invoke(null);
        b = rb.getMethod("selectors", selArr.getClass()).invoke(b, selArr);
        Object request = rb.getMethod("build").invoke(b);
        Class<?> lstC = Class.forName("org.junit.platform.launcher.listeners.SummaryGeneratingListener");
        Object listener = lstC.newInstance();
        Class<?> telC = Class.forName("org.junit.platform.launcher.TestExecutionListener");
        Object lArr = Array.newInstance(telC, 1);
        Array.set(lArr, 0, listener);
        Class<?> ldr = Class.forName("org.junit.platform.launcher.LauncherDiscoveryRequest");
        Class<?> launcherC = Class.forName("org.junit.platform.launcher.Launcher");
        launcherC.getMethod("execute", ldr, lArr.getClass()).invoke(launcher, request, lArr);
        Object sum = lstC.getMethod("getSummary").invoke(listener);
        long found = (Long) sum.getClass().getMethod("getTestsFoundCount").invoke(sum);
        long failed = (Long) sum.getClass().getMethod("getTotalFailureCount").invoke(sum);
        long skipped = (Long) sum.getClass().getMethod("getTestsSkippedCount").invoke(sum);
        if (failed > 0) {
            List<?> fl = (List<?>) sum.getClass().getMethod("getFailures").invoke(sum);
            String tr = "";
            if (!fl.isEmpty()) {
                Object f = fl.get(0);
                Throwable ex = (Throwable) f.getClass().getMethod("getException").invoke(f);
                tr = stack(ex);
            }
            return new String[]{"FAIL", tr};
        }
        if (found == 0) return new String[]{"NOT_FOUND", ""};
        if (skipped == found) return new String[]{"SKIPPED", ""};
        return new String[]{"PASS", ""};
    }

    // ----------------------------------------------------------------- list
    static void list(String out, File root) throws Exception {
        List<String> names = new ArrayList<String>();
        collect(root, root, names);
        PrintWriter pw = new PrintWriter(new OutputStreamWriter(new FileOutputStream(out), "UTF-8"));
        for (String n : names) pw.println(n);
        pw.close();
    }

    static void collect(File root, File f, List<String> out) {
        File[] kids = f.listFiles();
        if (kids == null) return;
        for (File k : kids) {
            if (k.isDirectory()) { collect(root, k, out); continue; }
            String p = k.getPath();
            if (!p.endsWith(".class") || p.contains("$")) continue;
            String rel = p.substring(root.getPath().length() + 1, p.length() - 6);
            String cn = rel.replace(File.separatorChar, '.');
            try {
                Class<?> c = Class.forName(cn, false, OrderRunner.class.getClassLoader());
                if (Modifier.isAbstract(c.getModifiers()) || c.isInterface()) continue;
                boolean junit3 = isJUnit3(c);
                for (Method m : c.getMethods()) {
                    boolean t = false;
                    for (Annotation a : m.getAnnotations()) {
                        String n = a.annotationType().getName();
                        if (n.equals("org.junit.Test") || n.equals("org.junit.jupiter.api.Test")
                            || n.equals("org.junit.jupiter.params.ParameterizedTest")) t = true;
                        if (n.equals("org.junit.Ignore") || n.equals("org.junit.jupiter.api.Disabled")) { t = false; break; }
                    }
                    if (!t && junit3 && m.getName().startsWith("test") && m.getParameterTypes().length == 0
                        && m.getReturnType() == void.class) t = true;
                    if (t) out.add(cn + "#" + m.getName());
                }
            } catch (Throwable e) {
                // class could not be loaded (missing optional dependency); skip it
            }
        }
    }

    static boolean isJUnit3(Class<?> c) {
        for (Class<?> k = c; k != null; k = k.getSuperclass())
            if (k.getName().equals("junit.framework.TestCase")) return true;
        return false;
    }

    // ---------------------------------------------------------------- utils
    static String stack(Throwable e) {
        StringWriter sw = new StringWriter();
        e.printStackTrace(new PrintWriter(sw));
        return sw.toString();
    }

    static String cut(String s, int n) { return s == null ? "" : (s.length() > n ? s.substring(0, n) : s); }

    static String q(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char ch : s.toCharArray()) {
            switch (ch) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (ch < 0x20) b.append(String.format("\\u%04x", (int) ch)); else b.append(ch);
            }
        }
        return b.append('"').toString();
    }
}
