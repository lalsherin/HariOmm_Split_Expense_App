import brut.androlib.src.SmaliBuilder;
import brut.directory.ExtFile;
import java.io.File;

public class Dexer {
    public static void main(String[] args) throws Exception {
        SmaliBuilder.build(new ExtFile(new File(args[0])), new File(args[1]), Integer.parseInt(args[2]));
        System.out.println("dex written: " + args[1] + " (" + new File(args[1]).length() + " bytes)");
    }
}
