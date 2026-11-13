// The coding panel: an editor with Run, like an online code playground.
// Every <div data-code-panel> holds a plain <textarea>, so the page works without this script
// (and the textarea is what forms send). This script turns it into a CodeMirror editor and
// runs the code in the learner's browser, never on our server:
//   python      Pyodide in a worker (static/js/python_worker.js), stopped after a time limit
//   javascript  a worker with console.log captured, stopped after a time limit
//   html        a sandboxed preview frame (HTML, CSS, and scripts that change the page)
//   sql         SQLite in the browser (sql.js), with the sample tables lessons use
//   java        editor only: Java needs a compiler, so learners run it in VS Code
(() => {
  if (window.codePanelsStarted) return;
  window.codePanelsStarted = true;

  const CM = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/";
  const SQLJS = "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/";
  const MODES = {
    python: ["python"], javascript: ["javascript"], html: ["xml", "javascript", "css", "htmlmixed"],
    sql: ["sql"], java: ["clike"],
  };
  const CM_MODE = {
    python: "python", javascript: "javascript", html: "htmlmixed", sql: "text/x-sqlite", java: "text/x-java",
  };
  const TIME_LIMIT = 8000; // ms of running before we stop it (after Python has loaded)

  // The tables SQL lessons and practice use, rebuilt fresh for every run.
  const SQL_SAMPLE = `
    CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, course TEXT, year INTEGER);
    INSERT INTO students VALUES (1,'Ana','BSCS',2),(2,'Ben','BSIT',1),(3,'Carla','BSCS',3),(4,'Dan','BSIT',2),(5,'Ella','BSCS',1);
    CREATE TABLE scores (name TEXT, score INTEGER);
    INSERT INTO scores VALUES ('Ana',88),('Ben',95),('Carla',79),('Dan',91),('Ella',84);
    CREATE TABLE enrollments (student_id INTEGER, subject TEXT);
    INSERT INTO enrollments VALUES (1,'Math'),(1,'Art'),(2,'Math'),(3,'Science'),(4,'Art');
    CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, author TEXT, price REAL, year INTEGER);
    INSERT INTO books VALUES (1,'Noli Me Tangere','Jose Rizal',350,1887),(2,'El Filibusterismo','Jose Rizal',380,1891),
      (3,'Dekada ''70','Lualhati Bautista',420,1983),(4,'Smaller and Smaller Circles','F.H. Batacan',550,2002),
      (5,'Insurrecto','Gina Apostol',600,2018);
  `;

  const loaded = {};
  function loadScript(src) {
    if (!loaded[src]) {
      loaded[src] = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = src;
        s.onload = resolve;
        s.onerror = () => reject(new Error(`Couldn't load ${src}`));
        document.head.appendChild(s);
      });
    }
    return loaded[src];
  }
  function loadCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }

  async function loadEditor(language) {
    loadCss(CM + "codemirror.min.css");
    await loadScript(CM + "codemirror.min.js");
    for (const mode of MODES[language] || []) await loadScript(`${CM}mode/${mode}/${mode}.min.js`);
  }

  // ----- Output -----

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function outputFor(panel) {
    const box = panel.querySelector("[data-code-output]");
    box.hidden = false;
    box.replaceChildren(el("p", "code-output-label", "Output"));
    const pre = el("pre", "code-output-text");
    box.appendChild(pre);
    return {
      box,
      write(text, kind) {
        const line = el("span", kind ? `code-out-${kind}` : "", text.endsWith("\n") ? text : text + "\n");
        pre.appendChild(line);
        pre.scrollTop = pre.scrollHeight;
      },
      empty() {
        return !pre.textContent;
      },
    };
  }

  // ----- Runners -----

  let pythonWorker = null;
  let pythonReady = false;
  function freshPythonWorker() {
    pythonWorker = new Worker(document.querySelector("[data-python-worker]").dataset.pythonWorker);
    pythonReady = false;
  }

  function runPython(code, panel, out) {
    if (!pythonWorker) freshPythonWorker();
    const stdin = panel.querySelector("[data-code-stdin]");
    return new Promise((resolve) => {
      let timer = null;
      const finish = () => {
        clearTimeout(timer);
        pythonWorker.onmessage = null;
        resolve();
      };
      const startTimer = () => {
        timer = setTimeout(() => {
          pythonWorker.terminate();
          freshPythonWorker();
          out.write("Stopped: your code ran for too long. Check for a loop that never ends.", "err");
          finish();
        }, TIME_LIMIT);
      };
      if (!pythonReady) out.write("Starting Python… (only the first time, a few seconds)", "note");
      else startTimer();
      pythonWorker.onmessage = ({ data }) => {
        if (data.type === "ready") {
          pythonReady = true;
          out.box.querySelector(".code-out-note")?.remove();
          startTimer();
        } else if (data.type === "out") out.write(data.text);
        else if (data.type === "err") out.write(data.text, "err");
        else if (data.type === "error") {
          out.write(data.text, "err");
          if (data.text.includes("EOFError")) out.write("Your code asks for input(). Type answers in “Input for your program”, one per line.", "note");
          finish();
        } else if (data.type === "done") finish();
      };
      pythonWorker.postMessage({ code, input: stdin ? stdin.value : "" });
    });
  }

  const JS_WORKER = `
    const show = (v) => typeof v === "string" ? v : (() => { try { return JSON.stringify(v); } catch { return String(v); } })();
    const send = (type) => (...args) => postMessage({ type, text: args.map(show).join(" ") });
    console.log = console.info = send("out");
    console.error = console.warn = send("err");
    onmessage = (e) => {
      try { new Function(e.data)(); postMessage({ type: "done" }); }
      catch (error) { postMessage({ type: "error", text: error.name + ": " + error.message }); }
    };`;

  function runJavaScript(code, panel, out) {
    if (/\bdocument\b|\bwindow\b|\balert\s*\(/.test(code)) {
      out.write("This code uses the page (document or window). Try it in an HTML page with a <script> tag, like in the “Changing the page” lesson.", "note");
    }
    const url = URL.createObjectURL(new Blob([JS_WORKER], { type: "text/javascript" }));
    const worker = new Worker(url);
    return new Promise((resolve) => {
      const finish = () => {
        clearTimeout(timer);
        worker.terminate();
        URL.revokeObjectURL(url);
        resolve();
      };
      const timer = setTimeout(() => {
        out.write("Stopped: your code ran for too long. Check for a loop that never ends.", "err");
        finish();
      }, TIME_LIMIT);
      worker.onmessage = ({ data }) => {
        if (data.type === "out") out.write(data.text);
        else if (data.type === "err") out.write(data.text, "err");
        else {
          if (data.type === "error") out.write(data.text, "err");
          finish();
        }
      };
      worker.postMessage(code);
    });
  }

  // Console messages from inside the preview frame, so scripts' console.log shows too.
  const FRAME_CONSOLE = `<script>(() => {
    const send = (kind) => (...a) => parent.postMessage({ codePanel: true, kind, text: a.map(String).join(" ") }, "*");
    console.log = console.info = send("out"); console.error = console.warn = send("err");
    addEventListener("error", (e) => send("err")(e.message));
  })();<\/script>`;

  function runHtml(code, panel, out) {
    const looksLikeCss = !/<[a-z!]/i.test(code);
    const page = looksLikeCss
      ? `<!doctype html><html><head><style>${code}</style></head><body><h1>Heading</h1><p>A paragraph with <a href="#">a link</a>.</p><div class="card">A box with the class card</div><button>A button</button></body></html>`
      : code;
    const frame = el("iframe", "code-preview");
    frame.title = "Preview of your page";
    frame.setAttribute("sandbox", "allow-scripts allow-modals");
    frame.srcdoc = FRAME_CONSOLE + page;
    out.box.querySelector(".code-output-label").textContent = "Your page";
    out.box.insertBefore(frame, out.box.querySelector("pre"));
    const listen = ({ data, source }) => {
      if (data && data.codePanel && source === frame.contentWindow) out.write(data.text, data.kind === "err" ? "err" : "");
    };
    window.addEventListener("message", listen);
    panel.addEventListener("code-panel-rerun", () => window.removeEventListener("message", listen), { once: true });
    return Promise.resolve();
  }

  let sqlReady = null;
  async function runSql(code, panel, out) {
    if (!sqlReady) {
      sqlReady = loadScript(SQLJS + "sql-wasm.js").then(() => window.initSqlJs({ locateFile: (f) => SQLJS + f }));
    }
    const SQL = await sqlReady;
    const db = new SQL.Database();
    try {
      db.run(SQL_SAMPLE);
      const results = db.exec(code);
      if (!results.length) out.write("Done. (That query doesn't return any rows.)", "note");
      results.forEach((result) => {
        const table = el("table", "code-result");
        const head = table.createTHead().insertRow();
        result.columns.forEach((c) => head.appendChild(el("th", "", c)));
        const body = table.createTBody();
        result.values.forEach((row) => {
          const tr = body.insertRow();
          row.forEach((v) => tr.appendChild(el("td", "", v === null ? "NULL" : String(v))));
        });
        const wrap = el("div", "code-result-wrap");
        wrap.appendChild(table);
        out.box.insertBefore(wrap, out.box.querySelector("pre"));
        out.write(`${result.values.length} row${result.values.length === 1 ? "" : "s"}`, "note");
      });
    } catch (error) {
      out.write(String(error.message || error), "err");
    } finally {
      db.close();
    }
  }

  const RUNNERS = { python: runPython, javascript: runJavaScript, html: runHtml, sql: runSql };

  // ----- Panels -----

  function setUp(panel) {
    const language = panel.dataset.language;
    const textarea = panel.querySelector("textarea[data-code-source]");
    const original = textarea.value;
    const runButton = panel.querySelector("[data-code-run]");
    let editor = null;

    loadEditor(language).then(() => {
      editor = window.CodeMirror.fromTextArea(textarea, {
        mode: CM_MODE[language],
        lineNumbers: true,
        indentUnit: language === "python" || language === "java" ? 4 : 2,
        tabSize: 4,
        lineWrapping: false,
        inputStyle: "contenteditable", // better with phone keyboards
        viewportMargin: Infinity,
        extraKeys: {
          Tab: (cm) => (cm.somethingSelected() ? cm.indentSelection("add") : cm.replaceSelection(" ".repeat(cm.getOption("indentUnit")))),
          "Ctrl-Enter": () => runButton && runButton.click(),
          "Cmd-Enter": () => runButton && runButton.click(),
        },
      });
      editor.on("change", () => editor.save());
      panel.classList.add("code-panel-ready");
      // Panels inside a closed <details> measure themselves when opened.
      const details = panel.closest("details");
      if (details) details.addEventListener("toggle", () => details.open && editor.refresh());
    }).catch(() => {
      panel.classList.add("code-panel-plain"); // the textarea still works
    });

    const reset = panel.querySelector("[data-code-reset]");
    if (reset) {
      reset.addEventListener("click", () => {
        if (editor) editor.setValue(original);
        else textarea.value = original;
      });
    }

    if (runButton) {
      runButton.addEventListener("click", async () => {
        if (runButton.disabled) return;
        const code = editor ? editor.getValue() : textarea.value;
        panel.dispatchEvent(new Event("code-panel-rerun"));
        const out = outputFor(panel);
        runButton.disabled = true;
        runButton.classList.add("is-running");
        try {
          await RUNNERS[language](code, panel, out);
          if (out.empty() && language !== "html" && language !== "sql") {
            out.write(`(No output. Use ${language === "python" ? "print()" : "console.log()"} to show something.)`, "note");
          }
        } catch (error) {
          out.write("The runner couldn't start. Check your internet connection and try again.", "err");
        } finally {
          runButton.disabled = false;
          runButton.classList.remove("is-running");
        }
      });
    }
  }

  function init() {
    document.querySelectorAll("[data-code-panel]").forEach(setUp);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
