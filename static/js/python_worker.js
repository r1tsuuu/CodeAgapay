// Runs learners' Python in a Web Worker with Pyodide (real Python compiled to WebAssembly).
// A worker keeps the page responsive, and the page can stop it if the code never ends.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let ready = null;

function start() {
  if (!ready) {
    ready = loadPyodide().then((pyodide) => {
      postMessage({ type: "ready" });
      return pyodide;
    });
  }
  return ready;
}

onmessage = async (event) => {
  const { code, input } = event.data;
  const pyodide = await start();
  const lines = (input || "").split("\n");
  let next = 0;
  pyodide.setStdin({ stdin: () => (next < lines.length ? lines[next++] : null), autoEOF: true });
  pyodide.setStdout({ batched: (text) => postMessage({ type: "out", text }) });
  pyodide.setStderr({ batched: (text) => postMessage({ type: "err", text }) });
  try {
    // A fresh namespace each run, so old variables don't leak into the next try.
    const scope = pyodide.globals.get("dict")();
    await pyodide.runPythonAsync(code, { globals: scope });
    scope.destroy();
    postMessage({ type: "done" });
  } catch (error) {
    // Keep the last part of the traceback: the line and the error a beginner needs.
    const text = String(error.message || error);
    const parts = text.trim().split("\n");
    const start = parts.findIndex((line) => line.includes('File "<exec>"'));
    postMessage({ type: "error", text: (start >= 0 ? parts.slice(start) : parts.slice(-3)).join("\n") });
  }
};

start();
