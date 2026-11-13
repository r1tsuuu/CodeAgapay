// The mascots come alive: they arrive once, breathe, blink, watch the pointer, and hop when touched.
// Every mascot is a <span class="critter"> holding an inline SVG. Its eyes are found by drawing:
// white shapes are eye whites, and dark shapes sitting inside them are pupils. So any mascot from
// Figma works without hand-made markup.
//
// Motion budget (rare page, first visit): the arrival is the one entrance; hops answer the pointer;
// breathing and blinking are the idle life. Reduced motion keeps the blink only.
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const EASE_OUT = "cubic-bezier(0.23, 1, 0.32, 1)";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const critters = [];

  const fill = (el) => (el.getAttribute("fill") || "").toLowerCase();
  const isWhite = (el) => ["white", "#fff", "#ffffff"].includes(fill(el));
  // black, or Figma's near-blacks like #0A0000 and #070707
  const isDark = (el) => fill(el) === "black" || /^#0[0-9a-f]0[0-9a-f]0[0-9a-f]$/.test(fill(el));
  const random = (min, max) => min + Math.random() * (max - min);

  function group(className) {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", className);
    return g;
  }

  function centerOf(rect) {
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  // Gather a mascot's eye whites and pupils into groups the script can move.
  function findEyes(svg) {
    // Some drawings keep their parts in a <g>; work among the siblings of the first eye white.
    const firstWhite = [...svg.querySelectorAll("*")].find(isWhite);
    if (!firstWhite) return null;
    const shapes = [...firstWhite.parentNode.children];
    const whites = shapes.filter(isWhite);

    const whiteBoxes = whites.map((w) => w.getBoundingClientRect());
    const inAWhite = (el) => {
      const c = centerOf(el.getBoundingClientRect());
      return whiteBoxes.some((b) => c.x >= b.left && c.x <= b.right && c.y >= b.top && c.y <= b.bottom);
    };
    const first = shapes.indexOf(whites[0]);
    const pupils = shapes.filter((el, i) => i > first && isDark(el) && inAWhite(el));

    const eyes = group("critter-eyes");
    const pupilGroup = group("critter-pupils");
    firstWhite.parentNode.insertBefore(eyes, whites[0]);
    whites.forEach((w) => eyes.appendChild(w));
    pupils.forEach((p) => pupilGroup.appendChild(p));
    eyes.appendChild(pupilGroup);

    // How far a pupil may travel, in the drawing's own units: a slice of the eye's size.
    const box = whites[0].getBBox();
    return { eyes, pupils: pupilGroup, reach: Math.min(box.width, box.height) * 0.18 };
  }

  function blink(critter) {
    critter.eyes.animate(
      [{ transform: "scaleY(1)" }, { transform: "scaleY(0.08)" }, { transform: "scaleY(1)" }],
      { duration: 170, easing: "ease-in-out" }
    );
  }

  function scheduleBlink(critter) {
    critter.blinkTimer = setTimeout(() => {
      if (!document.hidden) {
        blink(critter);
        // Now and then a quick double blink, like a real double-take.
        if (Math.random() < 0.2) setTimeout(() => blink(critter), 240);
      }
      scheduleBlink(critter);
    }, random(2600, 7000));
  }

  function look(critter, target) {
    if (!critter.pupils) return;
    let x = 0;
    let y = 0;
    if (target) {
      const c = centerOf(critter.eyes.getBoundingClientRect());
      const dx = target.x - c.x;
      const dy = target.y - c.y;
      const distance = Math.hypot(dx, dy) || 1;
      // Full reach once the pointer is a little way off; softer when it's right on top of them.
      const strength = Math.min(1, distance / 260) * critter.reach;
      x = (dx / distance) * strength;
      y = (dy / distance) * strength;
    }
    critter.pupils.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`;
  }

  function glance(critter) {
    const angle = random(0, Math.PI * 2);
    const c = centerOf(critter.eyes.getBoundingClientRect());
    look(critter, Math.random() < 0.25 ? null : { x: c.x + Math.cos(angle) * 400, y: c.y + Math.sin(angle) * 400 });
  }

  function hop(critter, delay = 0) {
    if (reduce || critter.hopping || !critter.arrived) return;
    critter.hopping = true;
    const animation = critter.el.animate(
      [
        { transform: "translateY(0) scale(1, 1)" },
        { transform: "translateY(0) scale(1.06, 0.92)", offset: 0.15 },
        { transform: "translateY(-12%) scale(0.95, 1.06)", offset: 0.45 },
        { transform: "translateY(0) scale(1.05, 0.95)", offset: 0.78 },
        { transform: "translateY(0) scale(1, 1)" },
      ],
      { duration: 560, delay, easing: "ease-out" }
    );
    animation.onfinish = animation.oncancel = () => {
      critter.hopping = false;
    };
  }

  function setUp(el, order, count) {
    const svg = el.querySelector("svg");
    if (!svg) return;
    const critter = { el, svg, ...(findEyes(svg) || {}) };
    critters.push(critter);

    if (critter.eyes) scheduleBlink(critter);
    if (reduce) {
      critter.arrived = true;
      return;
    }

    // Arrive once: a short rise and settle, the group spread over about a second.
    const delay = 80 + (count > 1 ? (order / (count - 1)) * 520 : 0);
    el.animate(
      [
        { opacity: 0, transform: "translateY(18%) scale(0.9)" },
        { opacity: 1, transform: "translateY(0) scale(1)" },
      ],
      { duration: 620, delay, easing: EASE_OUT, fill: "backwards" }
    ).onfinish = () => {
      critter.arrived = true;
    };

    // Breathe: each at its own pace, so the crowd never moves in step.
    critter.breath = svg.animate(
      [
        { transform: "translateY(0) rotate(0deg)" },
        { transform: `translateY(-3%) rotate(${random(-2.5, 2.5).toFixed(2)}deg)` },
      ],
      { duration: random(2400, 3600), delay: -random(0, 3000), direction: "alternate", iterations: Infinity, easing: "ease-in-out" }
    );

    svg.addEventListener("pointerdown", () => hop(critter));
    if (finePointer) svg.addEventListener("pointerover", () => hop(critter));
  }

  function init() {
    const els = [...document.querySelectorAll(".critter")];
    // Arrive in reading order, top-left first, so the wave sweeps across the screen.
    const ordered = els
      .map((el) => ({ el, c: centerOf(el.getBoundingClientRect()) }))
      .sort((a, b) => a.c.x + a.c.y - (b.c.x + b.c.y));
    ordered.forEach(({ el }, i) => setUp(el, i, ordered.length));
    if (!critters.length) return;

    // Pause breathing for mascots off screen, so a long page doesn't paint what nobody sees.
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const critter = critters.find((c) => c.el === entry.target);
        if (critter && critter.breath) entry.isIntersecting ? critter.breath.play() : critter.breath.pause();
      });
    });
    critters.forEach((c) => seen.observe(c.el));

    if (reduce) return;

    // Eyes follow the pointer. With no pointer about (a phone, or it left the window), they glance around.
    let target = null;
    let frame = 0;
    let idleTimer = 0;
    let glanceTimer = 0;
    const update = () => {
      frame = 0;
      critters.forEach((c) => look(c, target));
    };
    const startGlancing = () => {
      target = null;
      clearInterval(glanceTimer);
      glanceTimer = setInterval(() => {
        const critter = critters[Math.floor(Math.random() * critters.length)];
        if (critter.pupils) glance(critter);
      }, 700);
    };
    const watch = (point) => {
      clearInterval(glanceTimer);
      clearTimeout(idleTimer);
      target = point;
      if (!frame) frame = requestAnimationFrame(update);
      idleTimer = setTimeout(startGlancing, 6000);
    };

    if (finePointer) {
      addEventListener("pointermove", (e) => watch({ x: e.clientX, y: e.clientY }), { passive: true });
      document.documentElement.addEventListener("pointerleave", startGlancing);
    }
    startGlancing();

    // A main button gets a cheer: everyone looks at it and hops in a wave.
    document.querySelectorAll("[data-mascot-cheer]").forEach((button) => {
      let last = 0;
      const cheer = () => {
        if (performance.now() - last < 1500) return;
        last = performance.now();
        watch(centerOf(button.getBoundingClientRect()));
        const visible = critters.filter((c) => {
          const r = c.el.getBoundingClientRect();
          return r.bottom > 0 && r.top < innerHeight;
        });
        visible.forEach((c, i) => hop(c, i * 35));
      };
      button.addEventListener("pointerenter", cheer);
      button.addEventListener("focus", cheer);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
