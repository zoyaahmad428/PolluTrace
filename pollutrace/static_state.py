"""Lightweight static analysis of Java test sources for shared-state reasoning.

No parser dependency: comments and string literals are stripped, then regular expressions
find (a) types the code refers to, resolved to fully qualified names through the imports and
the package, and (b) static-looking member accesses `Type.member` and `Type.member(...)`.
Two tests that touch the same static members are the most likely polluter/victim pairs
(iFixFlakies, Shi et al. 2019; PolluTrace G1). The same resolved types are the classes whose
static fields the state-diff agent snapshots (G2).
"""
import re

COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\'')
PKG_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
IMPORT_RE = re.compile(r"^\s*import\s+(static\s+)?([\w.]+)(\.\*)?\s*;", re.M)
TYPE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")
MEMBER_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*\.\s*([a-zA-Z_][A-Za-z0-9_]*)\b(\s*\()?")
FQ_RE = re.compile(r"\b((?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_]*)\b")
STATIC_FIELD_RE = re.compile(r"\bstatic\s+(?!class\b|interface\b|enum\b)(?:final\s+)?[\w<>\[\],.? ]+?\s+(\w+)\s*[=;]")

JAVA_LANG = {"String", "Integer", "Long", "Double", "Float", "Boolean", "Character", "Byte", "Short", "Object",
             "Math", "Thread", "Exception", "RuntimeException", "Throwable", "Error", "Class", "Override",
             "Deprecated", "SuppressWarnings", "StringBuilder", "Number", "Void", "Iterable", "Runnable",
             "IllegalArgumentException", "IllegalStateException", "NullPointerException", "AssertionError",
             "Assert", "Assertions", "Test", "Before", "After", "BeforeClass", "AfterClass", "BeforeEach",
             "AfterEach", "BeforeAll", "AfterAll", "Rule", "ClassRule", "RunWith", "Mock", "Mockito",
             "Matchers", "CoreMatchers", "Ignore", "Disabled", "TestCase", "Arrays", "Collections", "List",
             "Map", "Set", "ArrayList", "HashMap", "HashSet", "Optional", "TimeUnit", "SECONDS", "MILLISECONDS"}
# System and a few JDK globals are real shared state, so they are kept as members (System.setProperty ...)
GLOBAL_STATE = {"System", "Locale", "TimeZone", "Runtime", "Security", "Thread", "URL", "HttpURLConnection",
                "Logger", "LogManager", "Charset", "DateTimeZone", "ThreadLocal"}


def strip(src):
    src = COMMENT_RE.sub(" ", src)
    return STRING_RE.sub('""', src)


def package(src):
    m = PKG_RE.search(src)
    return m.group(1) if m else ""


def imports(src):
    single, wild, static = {}, [], []
    for m in IMPORT_RE.finditer(src):
        is_static, name, star = m.group(1), m.group(2), m.group(3)
        if is_static:
            static.append(name + (".*" if star else ""))
        elif star:
            wild.append(name)
        else:
            single[name.rsplit(".", 1)[-1]] = name
    return single, wild, static


def analyse(src):
    """Returns dict(package, types={simple: fq-or-None}, members={'Type.member'}, static_fields=[...])."""
    if not src:
        return {"package": "", "types": {}, "members": set(), "static_fields": [], "static_imports": []}
    clean = strip(src)
    pkg = package(clean)
    single, wild, static = imports(clean)
    body = IMPORT_RE.sub(" ", PKG_RE.sub(" ", clean))
    types = {}
    for t in set(TYPE_RE.findall(body)):
        if t in JAVA_LANG and t not in GLOBAL_STATE:
            continue
        if t.isupper() and len(t) > 1:  # CONSTANT_NAME, not a type
            continue
        types[t] = single.get(t)
    for fq in FQ_RE.findall(body):
        types.setdefault(fq.rsplit(".", 1)[-1], fq)
    members = set()
    for typ, mem, call in MEMBER_RE.findall(body):
        if (typ in JAVA_LANG and typ not in GLOBAL_STATE) or mem in ("class", "this"):
            continue
        members.add(f"{typ}.{mem}{'()' if call else ''}")
    for s in static:  # import static a.b.C.field -> C.field
        parts = s.split(".")
        if len(parts) >= 2 and parts[-1] != "*":
            members.add(f"{parts[-2]}.{parts[-1]}")
    return {"package": pkg, "types": types, "members": members, "wild": wild,
            "static_fields": STATIC_FIELD_RE.findall(body), "static_imports": static}


def candidate_classes(info, limit=150):
    """Fully qualified class names whose static fields are worth snapshotting."""
    out = []
    for simple, fq in sorted(info["types"].items()):
        if fq:
            out.append(fq)
        else:
            if info["package"]:
                out.append(f"{info['package']}.{simple}")
            out.extend(f"{w}.{simple}" for w in info.get("wild", []))
    for s in info.get("static_imports", []):
        out.append(s[:-2] if s.endswith(".*") else s.rsplit(".", 1)[0])
    seen, res = set(), []
    for c in out:
        if c not in seen and not c.startswith("java.lang."):
            seen.add(c)
            res.append(c)
    return res[:limit]


def method_source(src, method):
    """Source text of one method (signature through closing brace), or None."""
    if not src:
        return None
    m = re.search(r"(?:@[\w.]+(?:\([^)]*\))?\s*)*(?:public|protected|private|static|final|synchronized|\s)*"
                  r"[\w<>\[\],.? ]+\s+" + re.escape(method) + r"\s*\([^)]*\)[^{;]*\{", src)
    if not m:
        return None
    depth = 0
    for j in range(m.end() - 1, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1].strip()
    return None


def lifecycle_methods(src):
    """Setup/teardown methods of a test class (where pollution is usually created or cleaned)."""
    out = []
    for ann in ("Before", "After", "BeforeClass", "AfterClass", "BeforeEach", "AfterEach", "BeforeAll", "AfterAll"):
        for m in re.finditer(r"@" + ann + r"\b[^\n]*\n\s*(?:public|protected|private|static|final|\s)*void\s+(\w+)", src or ""):
            body = method_source(src, m.group(1))
            if body:
                out.append(body)
    for name in ("setUp", "tearDown"):  # JUnit 3
        body = method_source(src, name)
        if body and body not in out:
            out.append(body)
    return out


def trace_types(trace):
    """Simple class names that appear in stack-trace frames and exception messages."""
    names = set(re.findall(r"\bat\s+(?:[\w$]+\.)*([A-Z][\w$]*)\.[\w$<>]+\(", trace or ""))
    names |= set(re.findall(r"\b(?:[a-z_][\w]*\.)+([A-Z][\w]*)\b", trace or ""))
    return {n.split("$")[0] for n in names}


def shared_state_score(victim_info, cand_info, trace_names=(), same_class=False, cand_method_src=None):
    """Score how likely a candidate test pollutes the victim. Higher = more suspicious.
    Uses the candidate method body when available, otherwise its whole class."""
    cm = analyse(cand_method_src)["members"] if cand_method_src else cand_info["members"]
    shared_members = victim_info["members"] & (cm | cand_info["members"])
    shared_types = set(victim_info["types"]) & set(cand_info["types"])
    s = 3.0 * len(shared_members & cm) + 1.0 * len(shared_members - cm) + 0.5 * len(shared_types)
    s += 1.5 * len(shared_types & set(trace_names))
    s += 2.0 * len({m.split(".")[0] for m in cm} & GLOBAL_STATE & {m.split(".")[0] for m in victim_info["members"]})
    if same_class:
        s += 2.0
    if victim_info["package"] and victim_info["package"] == cand_info["package"]:
        s += 0.5
    return round(s, 2), sorted(shared_members)[:12]
