package android.app;
public class Activity extends android.content.Context { public static android.content.Intent started; public static int uiRuns;
  public void runOnUiThread(Runnable r) { uiRuns++; r.run(); }
  public void startActivity(android.content.Intent i) { started = i; } }
