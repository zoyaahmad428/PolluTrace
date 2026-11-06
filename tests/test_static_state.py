import unittest

from pollutrace import static_state as ss

VICTIM = """package com.acme;
import com.acme.cache.Registry;
import static org.junit.Assert.assertEquals;
public class VictimTest {
    // Registry.ignored() in a comment
    @Test public void readsRegistry() {
        String s = "Registry.inString()";
        assertEquals(1, Registry.size());
        System.getProperty("acme.mode");
    }
}
"""
POLLUTER = """package com.acme;
import com.acme.cache.Registry;
public class PolluterTest {
    @Test public void writes() { Registry.register("x"); System.setProperty("acme.mode", "a"); }
    @Test public void unrelated() { int x = 1; }
}
"""


class StaticStateTest(unittest.TestCase):
    def test_analyse_resolves_imports_and_skips_comments_and_strings(self):
        info = ss.analyse(VICTIM)
        self.assertEqual(info["package"], "com.acme")
        self.assertEqual(info["types"]["Registry"], "com.acme.cache.Registry")
        self.assertIn("Registry.size()", info["members"])
        self.assertNotIn("Registry.ignored()", info["members"])
        self.assertNotIn("Registry.inString()", info["members"])
        self.assertIn("System.getProperty()", info["members"])

    def test_candidate_classes(self):
        cls = ss.candidate_classes(ss.analyse(VICTIM))
        self.assertIn("com.acme.cache.Registry", cls)
        self.assertIn("com.acme.VictimTest", cls)

    def test_method_source_and_score(self):
        body = ss.method_source(POLLUTER, "writes")
        self.assertIn("Registry.register", body)
        self.assertTrue(body.rstrip().endswith("}"))
        v, p = ss.analyse(VICTIM), ss.analyse(POLLUTER)
        s_writes, _ = ss.shared_state_score(v, p, cand_method_src=ss.method_source(POLLUTER, "writes"))
        s_unrel, _ = ss.shared_state_score(v, p, cand_method_src=ss.method_source(POLLUTER, "unrelated"))
        self.assertGreater(s_writes, s_unrel)

    def test_trace_types(self):
        t = "java.lang.AssertionError\n\tat com.acme.cache.Registry.size(Registry.java:10)\n\tat com.acme.VictimTest.readsRegistry(VictimTest.java:8)"
        self.assertTrue({"Registry", "VictimTest"} <= ss.trace_types(t))


if __name__ == "__main__":
    unittest.main()
