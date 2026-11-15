// The Agapay panel: "Need help?" opens it, questions go to /help/ask/, and replies
// step up from hint 1 to 3. AI text is only ever set with textContent, never as HTML.
(function () {
  var panel = document.getElementById("help-panel");
  var openButton = document.querySelector("[data-help-open]");
  if (!panel || !openButton) return;

  var form = panel.querySelector("[data-help-form]");
  var input = form.querySelector("#help-question"); // Not the first textarea: the debug boxes come before it.
  var send = form.querySelector("button");
  var log = panel.querySelector("[data-help-log]");
  var left = panel.querySelector("[data-help-left]");
  var fill = panel.querySelector(".help-meter-fill");
  var csrf = panel.querySelector("input[name=csrfmiddlewaretoken]").value;
  var limit = Number(panel.dataset.limit) || 1;
  var last = null; // {question, quizItem, answer, level, action}
  var busy = false;
  var action = "hint";
  var actionButtons = Array.prototype.slice.call(panel.querySelectorAll("[data-action]"));
  var debugBox = panel.querySelector("[data-help-debug]");
  var codeInput = panel.querySelector("#help-code");
  var errorInput = panel.querySelector("#help-error");
  var languageSelect = panel.querySelector("[data-help-language]");
  var languageChanged = false;
  var where = panel.dataset.lesson || panel.dataset.topic || "";
  var title = (panel.querySelector(".help-head-text p") || {}).textContent || "";
  title = title.replace("Helping with: ", "");

  // What each action asks when the learner sends without typing, and what the box suggests.
  var ACTIONS = {
    hint: { ask: "I'm stuck. Where do I start?", placeholder: "What are you stuck on?" },
    explain: { ask: "Explain " + title + " in simple words.", placeholder: "Which idea should I explain?" },
    debug: { ask: "Help me find the bug.", placeholder: "What should it do instead?" },
    check: { ask: "Check my understanding of " + title + ".", placeholder: "Anything in particular? (optional)" },
    breakdown: { ask: "Break this task into small steps.", placeholder: "Paste or describe the task" }
  };
  var LABELS = { hint: "Hint", explain: "Explanation", debug: "Debugging help", check: "Check your understanding",
                 breakdown: "Steps", solution: "Worked solution" };

  function selectAction(name) {
    action = name;
    actionButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.action === name)); });
    panel.querySelectorAll("[data-help-sheet]").forEach(function (sheet) {
      sheet.hidden = sheet.dataset.helpSheet !== name;
    });
    if (debugBox) debugBox.hidden = name !== "debug";
    form.hidden = name === "adjust" || name === "project";
    if (ACTIONS[name]) input.placeholder = ACTIONS[name].placeholder;
    if (name === "debug" && codeInput) codeInput.focus();
    else if (!form.hidden && !input.disabled) input.focus();
  }
  actionButtons.forEach(function (b) {
    b.addEventListener("click", function () { selectAction(b.dataset.action); });
  });
  if (languageSelect) languageSelect.addEventListener("change", function () { languageChanged = true; });

  function sendFeedback(card, data, rating, note) {
    return fetch(panel.dataset.feedbackUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      credentials: "same-origin",
      body: JSON.stringify({ where: where, action: data.action || "hint", mode: data.mode, rating: rating, note: note || "" })
    }).then(function (r) { return r.ok; }).catch(function () { return false; });
  }

  // Helpful / Not helpful, and "Report a problem" with a short note. Stores no question or reply.
  function feedbackRow(card, data) {
    var row = el("div", "help-feedback");
    var thanks = el("span", "help-feedback-thanks", "");
    thanks.setAttribute("role", "status");
    [["Helpful", 1], ["Not helpful", -1]].forEach(function (pair) {
      var b = el("button", "help-rate", pair[0]);
      b.type = "button";
      b.addEventListener("click", function () {
        row.querySelectorAll(".help-rate").forEach(function (x) { x.disabled = true; });
        sendFeedback(card, data, pair[1]).then(function (ok) { thanks.textContent = ok ? "Thanks!" : "Couldn't save that."; });
      });
      row.appendChild(b);
    });
    var report = el("button", "help-rate", "Report a problem");
    report.type = "button";
    report.addEventListener("click", function () {
      report.remove();
      var box = el("div", "help-report");
      var label = el("label", "", "What went wrong?");
      var note = el("textarea", "");
      note.rows = 2; note.maxLength = 500;
      note.id = "help-report-" + Date.now();
      label.htmlFor = note.id;
      var go = el("button", "help-rate", "Send report");
      go.type = "button";
      go.addEventListener("click", function () {
        if (!note.value.trim()) { note.focus(); return; }
        go.disabled = true;
        sendFeedback(card, data, 0, note.value).then(function (ok) {
          box.replaceWith(el("p", "help-feedback-thanks", ok ? "Thanks. The team will check it." : "Couldn't send that. Try again later."));
        });
      });
      box.appendChild(label); box.appendChild(note); box.appendChild(go);
      row.after(box);
      note.focus();
    });
    row.appendChild(report);
    row.appendChild(thanks);
    return row;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function open() {
    panel.hidden = false;
    openButton.setAttribute("aria-expanded", "true");
    document.body.classList.add("help-open");
    if (!input.disabled) input.focus();
  }

  function close() {
    panel.hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    document.body.classList.remove("help-open");
    openButton.focus();
  }

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function setRemaining(n) {
    left.textContent = n + " of " + limit + " messages left today";
    fill.style.width = Math.round((n * 100) / limit) + "%";
    if (n <= 0) {
      input.disabled = true;
      send.disabled = true;
      input.placeholder = "Today's AI help is used up. It resets tomorrow.";
    }
  }

  function related(data) {
    var box = el("div", "help-related");
    if (data.tips && data.tips.length) {
      box.appendChild(el("p", "help-related-label", "Related"));
      data.tips.slice(0, 2).forEach(function (tip) { box.appendChild(el("p", "help-tip", tip)); });
    }
    (data.resources || []).forEach(function (r) {
      var a = el("a", "help-link external", r.title);
      a.href = r.url;
      a.target = "_blank";
      a.rel = "noopener";
      box.appendChild(a);
    });
    return box.childNodes.length ? box : null;
  }

  function showReply(data) {
    var card = el("div", "help-reply");
    var kind = data.action || "hint";
    if (data.mode === "ai") {
      var level = el("span", "help-level", kind === "hint" ? "Hint " + data.hint_level + " of 3" : LABELS[kind] || "Agapay");
      if (kind === "hint") {
        // The hint ladder: one step per level, the newest one filling in.
        var ladder = el("span", "help-ladder");
        ladder.setAttribute("aria-hidden", "true");
        for (var i = 1; i <= 3; i++) {
          ladder.appendChild(el("span", i <= data.hint_level ? (i === data.hint_level ? "is-on is-new" : "is-on") : ""));
        }
        level.appendChild(ladder);
      }
      card.appendChild(level);
    }
    card.appendChild(el("p", "help-reply-text", data.reply));
    if (data.mode === "ai" && kind === "hint" && data.hint_level < 3) {
      var more = el("button", "help-more", "Another hint");
      more.type = "button";
      more.addEventListener("click", function () {
        more.remove();
        ask(last.question, last.level + 1, last.quizItem, last.answer, false, "hint");
      });
      card.appendChild(more);
    } else if (data.mode === "ai" && kind === "hint") {
      card.appendChild(el("p", "help-after", "That's 3 hints. The links below explain it fully, so give them a look."));
      // A full solution only when they ask for it, and never on a quiz.
      if (!last.quizItem && panel.dataset.screen !== "quiz") {
        var solve = el("button", "help-more", "Show me the full solution");
        solve.type = "button";
        solve.addEventListener("click", function () {
          var sure = el("div", "help-confirm");
          sure.appendChild(el("p", "", "This explains a complete answer step by step. You'll learn more if you try once more first. Still want it?"));
          var yes = el("button", "help-more", "Yes, explain the full solution");
          yes.type = "button";
          yes.addEventListener("click", function () {
            sure.remove();
            ask(last.question, 3, null, "", false, "solution");
          });
          sure.appendChild(yes);
          solve.replaceWith(sure);
        });
        card.appendChild(solve);
      }
    }
    if (data.mode === "ai") card.appendChild(feedbackRow(card, data));
    log.appendChild(card);
    var extra = related(data);
    if (extra && (data.mode !== "ai" || data.hint_level === 1 || data.hint_level === 3)) log.appendChild(extra);
    setRemaining(data.remaining_today);
    scrollDown();
  }

  function ask(question, level, quizItem, answer, showQuestion, kind) {
    if (busy) return;
    busy = true;
    kind = kind || "hint";
    last = { question: question, level: level, quizItem: quizItem, answer: answer, action: kind };
    var extra = { action: kind };
    if (kind === "debug" && codeInput) {
      extra.code = codeInput.value;
      extra.error = errorInput ? errorInput.value : "";
    }
    if (languageSelect && languageChanged) extra.language = languageSelect.value;
    if (showQuestion) log.appendChild(el("p", "help-question", question));
    var waiting = el("p", "help-waiting", "Agapay is thinking");
    waiting.setAttribute("role", "status");
    log.appendChild(waiting);
    scrollDown();
    send.disabled = true;
    panel.classList.add("is-thinking");

    fetch(panel.dataset.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      credentials: "same-origin",
      body: JSON.stringify({
        topic: panel.dataset.topic,
        lesson: panel.dataset.lesson || "",
        screen: quizItem ? "quiz" : panel.dataset.screen,
        question: question,
        hint_level: level,
        quiz_item_id: quizItem || "",
        learner_answer: answer || "",
        action: extra.action,
        code: extra.code || "",
        error: extra.error || "",
        language: extra.language
      })
    })
      .then(function (r) { return r.json(); })
      .catch(function () {
        return { mode: "fallback", reply: "Something went wrong. Try again in a moment.", hint_level: level, remaining_today: NaN };
      })
      .then(function (data) {
        waiting.remove();
        panel.classList.remove("is-thinking");
        if (isNaN(data.remaining_today)) data.remaining_today = Number(left.textContent.split(" ")[0]);
        showReply(data);
        busy = false;
        send.disabled = input.disabled;
      });
  }

  // Agapay says hi a few seconds in, once per lesson per visit, unless the panel is already open.
  var greeter = document.querySelector("[data-help-greeter]");
  function hideGreeter() {
    if (greeter) greeter.classList.remove("is-visible");
  }
  if (greeter) {
    var seenKey = "agapay-hi:" + greeter.dataset.key;
    var seen = false;
    try { seen = sessionStorage.getItem(seenKey) === "1"; } catch (e) { /* storage blocked: just show it */ }
    if (!seen) {
      setTimeout(function () {
        if (!panel.hidden) return;
        greeter.classList.add("is-visible");
        try { sessionStorage.setItem(seenKey, "1"); } catch (e) { /* fine without it */ }
        // It steps aside once they get to work, or after a while, so it never sits on a button.
        setTimeout(hideGreeter, 12000);
        document.addEventListener("keydown", hideGreeter, { once: true });
        document.addEventListener("pointerdown", function (e) {
          if (!greeter.contains(e.target)) hideGreeter();
        }, { once: true });
      }, 3500);
    }
    greeter.querySelector("[data-greeter-close]").addEventListener("click", hideGreeter);
    greeter.querySelector("[data-greeter-ask]").addEventListener("click", function () {
      hideGreeter();
      open();
    });
  }

  openButton.addEventListener("click", function () {
    hideGreeter();
    if (panel.hidden) open(); else close();
  });
  panel.querySelector("[data-help-close]").addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) close();
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (input.disabled) return;
    var typed = input.value.trim();
    var kind = ACTIONS[action] ? action : "hint";
    var question = typed || ACTIONS[kind].ask;
    input.value = "";
    ask(question, 1, null, "", true, kind);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // "Stuck? Ask Agapay" links from the plan land here with #agapay: open the panel straight away.
  if (location.hash === "#agapay") open();

  // "Why is this wrong?" / "Need help?" links on quiz screens ask about one blank.
  document.querySelectorAll("[data-help-ask]").forEach(function (link) {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      open();
      if (input.disabled) return;
      ask(link.dataset.helpAsk, 1, link.dataset.quizItem || null, link.dataset.answer || "", true);
    });
  });
})();
