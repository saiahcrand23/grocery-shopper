// Does every function the UI calls actually exist?
//
// Written after a cleanup regex silently deleted sharePdf while leaving its
// three call sites behind. That parses fine and throws ReferenceError on tap,
// so every print button did nothing — a syntax check can't see it.
//
// Evaluates the script's top-level declarations against a stub DOM, minus the
// boot lines at the end, then asks inside that scope which names are missing.
// typeof is safe on undeclared identifiers, and the probe has to run inside
// the eval because eval'd declarations don't reach globalThis.
const src = new TextDecoder().decode(imports.gi.GLib.file_get_contents('app.js')[1]);
const body = src.replace(/\nrender\(\);[\s\S]*$/, "\n");

const needed = [
  "sharePdf", "standalone",
  "renderShop", "renderOrder", "renderRecipes", "renderRecipeDetail", "renderRecipeEdit",
  "renderImport", "renderCook", "renderCookMode", "renderHist", "renderTrends",
  "renderManage", "manageItemsHTML", "rowHTML", "groupRowHTML",
  "saveDraft", "importFiles", "extractRecipe", "materializeIngredients", "pickItemFor",
  "suggestions", "analyze", "recipeAmounts",
  "addOneOff", "dropOneOff", "finalize", "addItem",
  "adoptServerSnapshot", "setPlannedDay", "planned", "toast", "sheet", "save",
];
const probe = `\nglobalThis.__kinds = {${needed.map(n => `${n}: typeof ${n}`).join(",")}};\n`;

const stub = () => new Proxy(function () {}, {
  get: () => stub(), apply: () => stub(), set: () => true,
});
globalThis.document = {
  querySelector: () => stub(), querySelectorAll: () => [],
  addEventListener() {}, createElement: () => stub(),
};
globalThis.window = { matchMedia: () => ({ matches: false }), addEventListener() {}, scrollTo() {}, navigator: {} };
globalThis.navigator = { serviceWorker: { register: () => ({ catch() {} }) } };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.fetch = () => Promise.resolve({ ok: true, json: () => ({}) });
globalThis.crypto = { randomUUID: () => "x" };

try {
  (0, eval)(body + probe);
} catch (e) {
  print("EVAL FAILED: " + e.message);
  imports.system.exit(1);
}

const missing = needed.filter(n => globalThis.__kinds[n] !== "function");
if (missing.length) {
  print("MISSING DEFINITIONS: " + missing.join(", "));
  imports.system.exit(1);
}
print(`all ${needed.length} referenced functions are defined`);
