// Small celebrations for big moments (a passed quiz, a finished plan):
//   [data-count-up]   a number that counts up from 0 to its value when it comes into view
//   [data-celebrate]  a burst of confetti in the brand colours, once per page per visit
// With "reduce motion" on, numbers show at once and there's no confetti.
(() => {
  if (window.celebrateStarted) return;
  window.celebrateStarted = true;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COLOURS = ["#C7366F", "#3CC6B6", "#FFB627", "#FF6B8B", "#B5D334", "#FF8A3D"];

  function countUp(el) {
    const target = Number(el.dataset.countUp);
    if (reduce || !Number.isFinite(target) || target <= 0) return;
    const suffix = el.dataset.countSuffix || "";
    const duration = Math.min(1200, 400 + target * 40);
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = Math.round(target * eased) + suffix;
      if (t < 1) requestAnimationFrame(step);
    };
    el.textContent = "0" + suffix;
    requestAnimationFrame(step);
  }

  function confetti(origin) {
    const layer = document.createElement("div");
    layer.className = "confetti-layer";
    layer.setAttribute("aria-hidden", "true");
    document.body.appendChild(layer);
    const box = origin.getBoundingClientRect();
    const x0 = box.left + box.width / 2;
    const y0 = Math.max(box.top + 40, 80);
    const pieces = innerWidth < 600 ? 36 : 60;
    let left = pieces;
    for (let i = 0; i < pieces; i++) {
      const piece = document.createElement("span");
      piece.className = "confetti-piece" + (i % 3 === 0 ? " confetti-round" : "");
      piece.style.background = COLOURS[i % COLOURS.length];
      piece.style.left = `${x0}px`;
      piece.style.top = `${y0}px`;
      layer.appendChild(piece);
      const angle = Math.random() * Math.PI - Math.PI; // upward half
      const speed = 160 + Math.random() * 260;
      const dx = Math.cos(angle) * speed;
      const dy = Math.sin(angle) * speed;
      const spin = (Math.random() - 0.5) * 720;
      piece.animate(
        [
          { transform: "translate(0, 0) rotate(0deg)", opacity: 1 },
          { transform: `translate(${dx}px, ${dy}px) rotate(${spin / 2}deg)`, opacity: 1, offset: 0.35 },
          { transform: `translate(${dx * 1.3}px, ${dy + 420}px) rotate(${spin}deg)`, opacity: 0 },
        ],
        { duration: 1500 + Math.random() * 700, easing: "cubic-bezier(0.2, 0.7, 0.4, 1)", fill: "forwards" }
      ).onfinish = () => {
        if (--left === 0) layer.remove();
      };
    }
  }

  function init() {
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        seen.unobserve(entry.target);
        countUp(entry.target);
      });
    });
    document.querySelectorAll("[data-count-up]").forEach((el) => seen.observe(el));

    if (reduce) return;
    document.querySelectorAll("[data-celebrate]").forEach((el) => {
      const key = "celebrated:" + location.pathname + ":" + (el.dataset.celebrate || "");
      try {
        if (sessionStorage.getItem(key)) return;
        sessionStorage.setItem(key, "1");
      } catch (e) { /* storage blocked: celebrate anyway */ }
      setTimeout(() => confetti(el), 350);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
