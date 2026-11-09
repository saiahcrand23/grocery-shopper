// Does the script parse? Compiling it in a Function catches syntax errors
// without running anything.
const src = new TextDecoder().decode(imports.gi.GLib.file_get_contents('app.js')[1]);
try {
  new Function(src);
  print("syntax ok");
} catch (e) {
  print("SYNTAX ERROR: " + e.message + (e.lineNumber ? "  (line " + e.lineNumber + ")" : ""));
  imports.system.exit(1);
}
