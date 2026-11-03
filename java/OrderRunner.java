import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.io.Writer;
import java.lang.annotation.Annotation;
import java.lang.reflect.Array;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.List;

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
        }
        System.exit(0); // do not wait for non-daemon threads left by tests
    }

    // ------------------------------------------------------------------ run
    static void run(String out, List<String> tests) throws Exception {
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
        sb.append("]}");
        Writer w = new OutputStreamWriter(new FileOutputStream(out), "UTF-8");
        w.write(sb.toString());
        w.close();
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
