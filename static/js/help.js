// The Agapay panel: "Need help?" opens it, questions go to /help/ask/, and replies
// step up from hint 1 to 3. AI text is only ever set with textContent, never as HTML.
(function () {
  var panel = document.getElementById("help-panel");
  var openButton = document.querySelector("[data-help-open]");
  if (!panel || !openButton) return;

  var form = panel.querySelector("[data-help-form]");
  var input = form.querySelector("textarea");
  var send = form.querySelector("button");
  var log = panel.querySelector("[data-help-log]");
  var left = panel.querySelector("[data-help-left]");
  var fill = panel.querySelector(".help-meter-fill");
  var csrf = panel.querySelector("input[name=csrfmiddlewaretoken]").value;
  var limit = Number(panel.dataset.limit) || 1;
  var last = null; // {question, quizItem, answer, level}
  var busy = false;

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
    if (data.mode === "ai") {
      card.appendChild(el("span", "help-level", "Hint " + data.hint_level + " of 3"));
    }
    card.appendChild(el("p", "help-reply-text", data.reply));
    if (data.mode === "ai" && data.hint_level < 3) {
      var more = el("button", "help-more", "Another hint");
      more.type = "button";
      more.addEventListener("click", function () {
        more.remove();
        ask(last.question, last.level + 1, last.quizItem, last.answer, false);
      });
      card.appendChild(more);
    } else if (data.mode === "ai") {
      card.appendChild(el("p", "help-after", "That's 3 hints. The links below explain it fully, so give them a look."));
    }
    log.appendChild(card);
    var extra = related(data);
    if (extra && (data.mode !== "ai" || data.hint_level === 1 || data.hint_level === 3)) log.appendChild(extra);
    setRemaining(data.remaining_today);
    scrollDown();
  }

  function ask(question, level, quizItem, answer, showQuestion) {
    if (busy) return;
    busy = true;
    last = { question: question, level: level, quizItem: quizItem, answer: answer };
    if (showQuestion) log.appendChild(el("p", "help-question", question));
    var waiting = el("p", "help-waiting", "Agapay is thinking…");
    waiting.setAttribute("role", "status");
    log.appendChild(waiting);
    scrollDown();
    send.disabled = true;

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
        learner_answer: answer || ""
      })
    })
      .then(function (r) { return r.json(); })
      .catch(function () {
        return { mode: "fallback", reply: "Something went wrong. Try again in a moment.", hint_level: level, remaining_today: NaN };
      })
      .then(function (data) {
        waiting.remove();
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
    var question = input.value.trim();
    if (!question || input.disabled) return;
    input.value = "";
    ask(question, 1, null, "", true);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

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
