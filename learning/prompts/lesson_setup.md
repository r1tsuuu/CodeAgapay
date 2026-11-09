version: lesson-setup-1
follows: docs/plan-framework.md section 5 (Setup). Added to the lesson prompt for setup lessons only, so other lessons don't spend tokens on it.

Setup rules:
- Setup lesson ("setup"): get a beginner fully ready for every later lesson, not just the first file. When the request says the app shows the install steps, leave "setup" out and write only the why, a short explanation of why one editor and one project folder matter for the lessons ahead, and the first-file check. Otherwise also return "setup": {"main": ["step", ...], "alternative": ["step", ...]}, one action per step, 5 to 10 steps each.
  - "main" uses the main way given: download it from its official site and install it; add any extension it names (inside the editor, from the Extensions view); make the project folder given in Documents; open that folder in the editor (File, Open Folder); create the first file inside it, named in lowercase with no spaces; write a tiny piece of code; save it (Ctrl+S, or Cmd+S on a Mac); see it work (for a web page, open the file in a browser and refresh after each save).
  - "alternative" uses the no-install way given, if any, with the same tiny code and how to save the work (an account, or copying it somewhere safe). Leave it empty if there is no no-install way.
  - The explanation says in a few sentences why the folder and the editor matter for the lessons ahead. The task is the last step: the tiny file working. Examples are optional; write no check questions, because the learner confirms setup by choosing the way they set up.
