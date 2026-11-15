// The landing page. Everything here is an enhancement: with no JavaScript, the goal links
// reload the page with ?goal=, every section is visible, and the hint demo shows hint 1.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Plan previews: a goal link swaps its group's panel in place instead of reloading.
  document.querySelectorAll("[data-preview-group]").forEach((group) => {
    const tabs = [...group.querySelectorAll("[data-preview-tab]")];
    const panels = [...group.querySelectorAll("[data-preview-panel]")];
    tabs.forEach((tab) => {
      tab.addEventListener("click", (event) => {
        event.preventDefault();
        const slug = tab.dataset.previewTab;
        tabs.forEach((t) => t.setAttribute("aria-current", t === tab ? "true" : "false"));
        panels.forEach((panel) => {
          const show = panel.dataset.previewPanel === slug;
          panel.hidden = !show;
          if (show && !reduce) {
            panel.classList.remove("is-swapping");
            void panel.offsetWidth; // Restart the swap animation.
            panel.classList.add("is-swapping");
          }
        });
        history.replaceState(null, "", `?goal=${slug}${location.hash}`);
      });
    });
  });

  // The sample help panel: the first hint shows, and each click adds the next level.
  const demo = document.querySelector("[data-hint-demo]");
  if (demo) {
    const hints = [...demo.querySelectorAll("[data-hint]")];
    const button = demo.querySelector("[data-hint-next]");
    let shown = hints.filter((hint) => !hint.hidden).length;
    button.addEventListener("click", () => {
      if (shown === hints.length) {
        hints.slice(1).forEach((hint) => (hint.hidden = true));
        shown = 1;
      } else {
        hints[shown].hidden = false;
        shown += 1;
      }
      button.textContent = shown === hints.length ? "Start over" : "Show the next hint";
    });
  }

  if (reduce || !("IntersectionObserver" in window)) return;

  // Headings rise in once as their section arrives. Content is never hidden without JavaScript,
  // and under reduced motion nothing moves.
  const reveals = [...document.querySelectorAll("[data-reveal]")];
  document.documentElement.classList.add("js-reveal");
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-in");
      revealObserver.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -10% 0px" });
  reveals.forEach((el, i) => {
    el.style.setProperty("--reveal-delay", `${(i % 2) * 80}ms`);
    revealObserver.observe(el);
  });

  // How it works: each step lights up as it reaches the middle of the screen, in order.
  const track = document.querySelector("[data-how-track]");
  if (track) {
    const steps = [...track.querySelectorAll("[data-how-step]")];
    track.classList.add("is-tracking");
    const stepObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const reached = steps.indexOf(entry.target);
        steps.forEach((step, i) => {
          if (i <= reached) step.classList.add("is-reached");
        });
        track.style.setProperty("--how-progress", String((reached + 1) / steps.length));
      });
    }, { rootMargin: "0px 0px -45% 0px" });
    steps.forEach((step) => stepObserver.observe(step));
  }
})();
