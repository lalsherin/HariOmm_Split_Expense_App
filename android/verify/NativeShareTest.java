import android.app.Activity;
import android.content.*;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Runs the real share-card native code (ShareProvider and
 *  MainActivity.shareImage → run → doShareImage), converted from the APK's
 *  dex, against small stand-ins for the Android classes it touches. Checks
 *  what Android would be handed: the file written, the provider's answers,
 *  and the share intent. See verify/README in verify_dex.sh. */
public class NativeShareTest {
  static int fails = 0;
  static void check(boolean ok, String what) { System.out.println((ok ? "PASS  " : "FAIL  ") + what); if (!ok) fails++; }

  public static void main(String[] a) throws Exception {
    File cache = Files.createTempDirectory("sbcache").toFile();
    Context.cache = cache;
    ContentProvider.ctx = new Context();
    // any PNG will do; without an argument, a 1x1 one
    byte[] png = a.length > 0 ? Files.readAllBytes(Paths.get(a[0])) : Base64.getDecoder().decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==");
    String b64 = Base64.getEncoder().encodeToString(png);
    String URI = "content://com.sherinlal.splitledger.share/split-buddy-card.png";

    Object act = Class.forName("com.sherinlal.splitledger.MainActivity").getConstructor().newInstance();
    String r = (String) act.getClass().getMethod("shareImage", String.class, String.class).invoke(act, b64, "Goa Trip | Rahul owes Sherin ₹1,350.00");
    File out = new File(new File(cache, "share"), "split-buddy-card.png");
    check("ok".equals(r), "shareImage returns ok");
    check(out.exists() && Arrays.equals(Files.readAllBytes(out.toPath()), png), "PNG written byte-for-byte to <cache>/share/split-buddy-card.png");
    Intent ch = Activity.started;
    check(ch != null && "CHOOSER".equals(ch.action), "share sheet (chooser) launched");
    Intent send = ch == null ? null : (Intent) ch.extras.get("target");
    check(send != null && "android.intent.action.SEND".equals(send.action), "ACTION_SEND");
    check(send != null && "image/png".equals(send.type), "type image/png");
    check(send != null && URI.equals(String.valueOf(send.extras.get("android.intent.extra.STREAM"))), "EXTRA_STREAM is the content:// URI");
    check(send != null && String.valueOf(send.extras.get("android.intent.extra.TEXT")).startsWith("Goa Trip"), "caption as EXTRA_TEXT");
    check(send != null && (send.flags & 1) == 1 && (ch.flags & 1) == 1, "FLAG_GRANT_READ_URI_PERMISSION on intent and chooser");
    check(send != null && send.clip != null && URI.equals(String.valueOf(send.clip.uri)), "ClipData carries the URI through the chooser");
    for (Object v : send == null ? List.of() : send.extras.values()) check(!String.valueOf(v).startsWith("file:"), "no file:// anywhere: " + v);

    Activity.started = null;
    r = (String) act.getClass().getMethod("shareImage", String.class, String.class).invoke(act, "%%% not base64 %%%", "");
    check("error".equals(r) && Activity.started == null, "bad image data: 'error', nothing launched");

    Object p = Class.forName("com.sherinlal.splitledger.ShareProvider").getConstructor().newInstance();
    Class<?> pc = p.getClass();
    check((Boolean) pc.getMethod("onCreate").invoke(p), "provider onCreate");
    check("image/png".equals(pc.getMethod("getType", Uri.class).invoke(p, Uri.parse(URI))), "getType image/png");
    MatrixCursor cur = (MatrixCursor) pc.getMethod("query", Uri.class, String[].class, String.class, String[].class, String.class).invoke(p, Uri.parse(URI), null, null, null, null);
    check(cur != null && Arrays.asList(cur.cols).equals(List.of("_display_name", "_size")) && cur.rows.size() == 1
          && "split-buddy-card.png".equals(cur.rows.get(0)[0]) && ((Long) cur.rows.get(0)[1]) == png.length, "query: name and size");
    ParcelFileDescriptor fd = (ParcelFileDescriptor) pc.getMethod("openFile", Uri.class, String.class).invoke(p, Uri.parse(URI), "r");
    check(fd != null && fd.file.getCanonicalPath().equals(out.getCanonicalPath()) && fd.mode == 0x10000000, "openFile: that file, read-only");
    Files.writeString(new File(cache, "secret.txt").toPath(), "x");
    for (String bad : new String[]{ "content://com.sherinlal.splitledger.share/secret.txt",
        "content://com.sherinlal.splitledger.share/../secret.txt", "content://com.sherinlal.splitledger.share/share/../../secret.txt",
        "content://com.sherinlal.splitledger.share/" }) {
      boolean refused = false;
      try { pc.getMethod("openFile", Uri.class, String.class).invoke(p, Uri.parse(bad), "r"); }
      catch (java.lang.reflect.InvocationTargetException e) { refused = e.getCause() instanceof FileNotFoundException; }
      check(refused, "refuses " + bad);
      check(pc.getMethod("query", Uri.class, String[].class, String.class, String[].class, String.class).invoke(p, Uri.parse(bad), null, null, null, null) == null, "query null for " + bad);
    }
    check(pc.getMethod("insert", Uri.class, ContentValues.class).invoke(p, Uri.parse(URI), null) == null, "insert refused");
    check((Integer) pc.getMethod("delete", Uri.class, String.class, String[].class).invoke(p, Uri.parse(URI), null, null) == 0, "delete refused");
    check((Integer) pc.getMethod("update", Uri.class, ContentValues.class, String.class, String[].class).invoke(p, Uri.parse(URI), null, null, null) == 0, "update refused");
    System.out.println(fails == 0 ? "native share: ALL PASS" : "native share: " + fails + " FAILED");
    System.exit(fails == 0 ? 0 : 1);
  }
}
