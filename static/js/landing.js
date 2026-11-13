// The landing page's sample help panel: the first hint shows, and each click adds the next of
// Agapay's three hint levels, then starts over.
(() => {
  const demo = document.querySelector("[data-hint-demo]");
  if (!demo) return;
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
})();
