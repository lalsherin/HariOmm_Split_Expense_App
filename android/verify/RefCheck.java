import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.util.*;

/** stdin: lines "Method|Field owner name desc". Checks each exists in android.jar
 *  (searching superclasses and interfaces), so a misspelt API in hand-written
 *  smali is caught before it becomes NoSuchMethodError on a phone. */
public class RefCheck {
    static String desc(Class<?> c) {
        if (c.isPrimitive()) {
            if (c == int.class) return "I"; if (c == void.class) return "V"; if (c == boolean.class) return "Z";
            if (c == long.class) return "J"; if (c == byte.class) return "B"; if (c == char.class) return "C";
            if (c == short.class) return "S"; if (c == float.class) return "F"; return "D";
        }
        if (c.isArray()) return "[" + desc(c.getComponentType()).replace('.', '/');
        return "L" + c.getName().replace('.', '/') + ";";
    }
    static String mdesc(Class<?>[] p, Class<?> r) {
        StringBuilder b = new StringBuilder("(");
        for (Class<?> x : p) b.append(desc(x));
        return b.append(")").append(desc(r)).toString();
    }
    static boolean has(Class<?> c, String kind, String name, String d, Set<Class<?>> seen) {
        if (c == null || !seen.add(c)) return false;
        if (kind.equals("Field")) {
            for (Field f : c.getDeclaredFields()) if (f.getName().equals(name) && desc(f.getType()).equals(d)) return true;
        } else if (name.equals("<init>")) {
            for (Constructor<?> m : c.getDeclaredConstructors()) if (mdesc(m.getParameterTypes(), void.class).equals(d)) return true;
            return false;
        } else {
            for (Method m : c.getDeclaredMethods()) if (m.getName().equals(name) && mdesc(m.getParameterTypes(), m.getReturnType()).equals(d)) return true;
        }
        if (has(c.getSuperclass(), kind, name, d, seen)) return true;
        for (Class<?> i : c.getInterfaces()) if (has(i, kind, name, d, seen)) return true;
        return false;
    }
    public static void main(String[] a) throws Exception {
        URLClassLoader cl = new URLClassLoader(new URL[]{ new File(a[0]).toURI().toURL() }, null);
        BufferedReader r = new BufferedReader(new InputStreamReader(System.in));
        int bad = 0, n = 0;
        for (String line; (line = r.readLine()) != null;) {
            String[] p = line.trim().split(" ");
            if (p.length != 4) continue;
            if (!p[1].startsWith("android/") && !p[1].startsWith("java/")) continue;
            n++;
            Class<?> c;
            try { c = Class.forName(p[1].replace('/', '.'), false, cl); }
            catch (Throwable t) { System.out.println("MISSING CLASS " + p[1]); bad++; continue; }
            if (!has(c, p[0], p[2], p[3], new HashSet<>())) { System.out.println("MISSING " + line); bad++; }
        }
        System.out.println("checked " + n + " framework reference(s), " + bad + " missing");
        System.exit(bad == 0 ? 0 : 1);
    }
}
