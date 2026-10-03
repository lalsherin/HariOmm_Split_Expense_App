import java.io.File;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.Enumeration;

/** Load and link every class in an app jar against the Android API jar, with
 *  the JVM verifier on. A type error in the bytecode (the kind ART reports as
 *  VerifyError) fails here as java.lang.VerifyError. */
public class VerifyLoad {
    public static void main(String[] a) throws Exception {
        URLClassLoader cl = new URLClassLoader(new URL[]{ new File(a[0]).toURI().toURL(), new File(a[1]).toURI().toURL() }, null);
        int n = 0, bad = 0;
        try (JarFile jf = new JarFile(a[0])) {
            for (Enumeration<JarEntry> e = jf.entries(); e.hasMoreElements();) {
                String name = e.nextElement().getName();
                if (!name.endsWith(".class")) continue;
                String cn = name.replace('/', '.').replace(".class", "");
                try {
                    Class<?> c = Class.forName(cn, false, cl);
                    c.getDeclaredMethods();               // forces linking...
                    java.lang.invoke.MethodHandles.lookup();
                    // ...and verification:
                    Class.forName(cn, true, cl);
                    n++;
                } catch (Throwable t) {
                    bad++;
                    System.out.println("FAIL " + cn + ": " + t);
                }
            }
        }
        System.out.println("verified " + n + " class(es), " + bad + " failed");
        System.exit(bad == 0 ? 0 : 1);
    }
}
