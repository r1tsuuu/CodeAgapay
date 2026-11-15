// The landing page. Everything here is an enhancement: with no JavaScript, the goal links
// reload the page with ?goal=, every section is visible, and the hint demo shows hint 1.
// GSAP (loaded from cdnjs with an integrity hash) runs the hero entrance and the scroll-linked
// "How it works" line; without it, the hero shows at once and the steps light up by observer.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const root = document.documentElement;
  const gsap = window.gsap;
  const ScrollTrigger = window.ScrollTrigger;

  // The page's one authored moment: the headline rises line by line out of a blur, the
  // highlighter draws under "something real", then the rest of the hero follows.
  function heroEntrance() {
    const lines = gsap.utils.toArray(".hero-line");
    const rest = gsap.utils.toArray("[data-hero-part]").filter((el) => !el.classList.contains("hero-line"));
    const mark = document.querySelector(".hero-mark");
    const stage = document.querySelector("[data-hero-stage]");
    if (mark) gsap.set(mark, { "--mark": 0 });
    root.classList.remove("hero-pending");
    gsap.timeline({ defaults: { ease: "expo.out" } })
      .from(lines, { autoAlpha: 0, y: 28, filter: "blur(10px)", duration: 1, stagger: 0.12, clearProps: "filter,transform" })
      .to(mark, { "--mark": 1, duration: 0.7, ease: "power3.inOut" }, "-=0.5")
      .from(rest, { autoAlpha: 0, y: 16, duration: 0.8, stagger: 0.08, clearProps: "transform" }, "-=0.55")
      .from(stage, { autoAlpha: 0, y: 40, scale: 0.96, duration: 1.1, clearProps: "transform" }, 0.3);
  }

  if (gsap && !reduce) heroEntrance();
  else root.classList.remove("hero-pending");

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

  // How it works: the line fills with the scroll itself, and each step lights up as the line reaches it.
  const track = document.querySelector("[data-how-track]");
  if (track && gsap && ScrollTrigger) {
    gsap.registerPlugin(ScrollTrigger);
    const steps = [...track.querySelectorAll("[data-how-step]")];
    track.classList.add("is-tracking");
    ScrollTrigger.create({
      trigger: track,
      start: "top 75%",
      end: "bottom 55%",
      scrub: 0.4,
      onUpdate: (self) => {
        track.style.setProperty("--how-progress", self.progress.toFixed(3));
        steps.forEach((step, i) => step.classList.toggle("is-reached", self.progress >= i / steps.length));
      },
    });
  } else if (track) {
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
