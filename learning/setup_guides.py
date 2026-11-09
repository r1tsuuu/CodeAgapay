"""Step-by-step setup guides for the tools CodeAgapay recommends (docs/plan-framework.md, Setup).

Installing an editor and making a project folder are the same for every learner and rarely
change, so they're written here, tested, with official links, instead of by the AI each time.
The AI writes only what fits the learner's plan: why setup matters for their project and the
first-file check. A track without a guide here falls back to steps written by the AI.

Steps follow the learner's computer (LearnerProfile.device): shortcuts, the file manager, how to
install, and which command to type. When it isn't known, they mention both Windows and Mac.

Each step is {"text": ..., "link": url or "", "link_text": ...}. Text marks code with backticks.
"""

VS_CODE_DOWNLOAD = "https://code.visualstudio.com/download"
COMPUTERS = ("windows", "mac", "linux")


def _step(text, link="", link_text=""):
    return {"text": text, "link": link, "link_text": link_text}


def _shortcut(device, keys):
    """e.g. Ctrl+S on Windows and Linux, Cmd+S on a Mac, both when we don't know."""
    if device == "mac":
        return f"Cmd+{keys}"
    if device in COMPUTERS:
        return f"Ctrl+{keys}"
    return f"Ctrl+{keys} (Cmd+{keys} on a Mac)"


def _files(device):
    return {"mac": "Finder", "windows": "File Explorer", "linux": "your file manager"}.get(
        device, "File Explorer (Finder on a Mac)")


def _extensions(device):
    return f"open the **Extensions** view ({_shortcut(device, 'Shift+X')})"


def _install_vs_code(device):
    how = {
        "windows": "Download the Windows version and run the installer. Tick **Add \"Open with Code\" action** when it asks.",
        "mac": "Download the Mac version, open the downloaded file, and drag **Visual Studio Code** into your "
               "**Applications** folder.",
        "linux": "Download the .deb package (Ubuntu, Debian) or .rpm package (Fedora) and open it to install, "
                 "or install VS Code from your software store.",
    }.get(device, "Download VS Code for your computer (Windows, Mac or Linux) and run the installer. On Windows, "
                  "tick **Add \"Open with Code\" action** when the installer asks.")
    return _step(f"{how} VS Code is free.", VS_CODE_DOWNLOAD, "Download VS Code")


def _folder(folder, device):
    return [
        _step(f"Make your project folder: open {_files(device)}, go to Documents, and create a new folder named "
              f"`{folder}`. Every file for this plan goes in it."),
        _step(f"Open VS Code, click **File** → **Open Folder**, and choose `{folder}`. If VS Code asks whether you "
              "trust the authors of the files, click **Yes, I trust the authors**."),
    ]


def _first_file(name, note="Use lowercase letters and no spaces in file names."):
    return _step(f"Make your first file: in the **Explorer** panel on the left, click the **New File** icon and name it "
                 f"`{name}`. {note}")


def _save(device):
    return _step(f"Save with {_shortcut(device, 'S')}. To never forget, turn on **File** → **Auto Save**.")


def _reopen(folder):
    return _step(f"Next time, open VS Code and click **File** → **Open Recent** → `{folder}`. Your files are right "
                 "where you left them.")


def _web(folder, first_file, first_code, device):
    return [
        _install_vs_code(device),
        _step(f"Add Live Server, so your page updates by itself when you save: in VS Code, {_extensions(device)}, "
              "search for `Live Server` by Ritwick Dey, and click **Install**.",
              "https://marketplace.visualstudio.com/items?itemName=ritwickdey.LiveServer", "Live Server"),
        *_folder(folder, device),
        _first_file(first_file),
        _step(f"Type `{first_code}` into the file."),
        _save(device),
        _step(f"See it: right-click `{first_file}` and choose **Open with Live Server**. Your browser opens the page. "
              f"Without Live Server, double-click the file in {_files(device)} instead, and refresh the browser "
              "after each save."),
        _reopen(folder),
    ]


def _python(folder, device):
    install = {
        "windows": "Install Python 3: download the Windows installer and run it. Tick **Add python.exe to PATH** "
                   "before you click **Install Now**.",
        "mac": "Install Python 3: download the macOS installer, open it and follow its steps.",
        "linux": "Python 3 is usually already there: open a terminal and type `python3 --version`. If you see a "
                 "version number, skip this step; if not, install `python3` from your software store.",
    }.get(device, "Install Python 3 from python.org. On Windows, tick **Add python.exe to PATH** before you "
                  "click **Install Now**.")
    run = {"windows": "`python hello.py`", "mac": "`python3 hello.py`", "linux": "`python3 hello.py`"}.get(
        device, "`python hello.py` (`python3 hello.py` on a Mac)")
    return [
        _step(install, "https://www.python.org/downloads/", "Download Python"),
        _install_vs_code(device),
        _step(f"Add the Python extension: in VS Code, {_extensions(device)}, search for `Python` (by Microsoft), "
              "and click **Install**.", "https://code.visualstudio.com/docs/python/python-tutorial", "VS Code's Python guide"),
        *_folder(folder, device),
        _first_file("hello.py"),
        _step('Type `print("Hello!")` into the file.'),
        _save(device),
        _step("Run it: click the **Run** button (a triangle) at the top right. `Hello!` appears in the terminal at the "
              f"bottom. You can also open **Terminal** → **New Terminal** and type {run}."),
        _reopen(folder),
    ]


def _java(folder, device):
    return [
        _install_vs_code(device),
        _step(f"Add Java: in VS Code, {_extensions(device)}, search for `Extension Pack for Java` (by Microsoft), "
              "and click **Install**. If it says no JDK was found, follow its **Install JDK** button.",
              "https://code.visualstudio.com/docs/java/java-tutorial", "VS Code's Java guide"),
        *_folder(folder, device),
        _first_file("Hello.java", "In Java, the file name matches the class name, capital letter included."),
        _step('Type `public class Hello { public static void main(String[] args) { System.out.println("Hello!"); } }` '
              "into the file."),
        _save(device),
        _step("Run it: click **Run** just above the `main` line. `Hello!` appears in the terminal at the bottom."),
        _reopen(folder),
    ]


def _codepen(project):
    return [
        _step("Open CodePen in your browser.", "https://codepen.io", "CodePen"),
        _step("Sign up for a free account (**Sign Up**, top right), so your work is saved. You can use your Google account."),
        _step("Start a project: click **Pen** (or **Start Coding**). You get three boxes: HTML, CSS and JS, with your page "
              "showing below them."),
        _step("Type `<h1>Hello!</h1>` in the **HTML** box. It appears in the preview right away."),
        _step(f"Click **Save** and name the Pen `{project}`. Save again after every change."),
        _step("Next time, sign in and open **Your Work** to find your Pen."),
    ]


def _colab(project):
    return [
        _step("Open Google Colab in your browser and sign in with your Google account.",
              "https://colab.research.google.com", "Google Colab"),
        _step("Start a project: click **File** → **New notebook**."),
        _step(f"Rename it: click the name at the top left and call it `{project}`."),
        _step('In the first code cell, type `print("Hello!")` and tap the **Run** button on its left. `Hello!` '
              "appears below the cell."),
        _step("Colab saves to your Google Drive by itself, in the **Colab Notebooks** folder."),
        _step("Next time, open Colab and pick your notebook from the list (or from Google Drive)."),
    ]


def needs_a_computer(device):
    """VS Code and installers don't run on phones or tablets, and need extra setup on a Chromebook."""
    return device in ("phone", "chromebook")


def guide(track_slug, way, folder, device=""):
    """The built-in steps for a track's setup way ("main" or "alternative"), or [] when there's none."""
    if way == "main":
        if track_slug in ("html", "css"):
            return _web(folder, "index.html", "<h1>Hello!</h1>", device)
        if track_slug == "javascript":
            return _web(folder, "index.html", '<script>alert("Hello!")</script>', device)
        if track_slug == "python":
            return _python(folder, device)
        if track_slug == "java":
            return _java(folder, device)
        return []
    if track_slug in ("html", "css", "javascript"):
        return _codepen(folder)
    if track_slug == "python":
        return _colab(folder)
    return []


# --- How to try a lesson's task in the learner's setup ------------------------------------------

DEFAULT_FILES = {"html": "practice.html", "css": "style.css", "javascript": "script.js", "python": "practice.py",
                 "java": "Practice.java", "sql": "practice.sql"}
CODEPEN_BOX = {"html": "HTML", "css": "CSS", "javascript": "JS"}


def _see_it(lang, file, device, live_server=True):
    if lang == "python":
        return _step("Run it: click the **Run** button (a triangle) at the top right, and look at the terminal at the "
                     "bottom.")
    if lang == "java":
        return _step("Run it: click **Run** just above the `main` line, and look at the terminal at the bottom.")
    if lang == "css":
        page = "your page"
    elif lang == "javascript":
        page = "the page that loads it"
    else:
        page = f"`{file}`"
    if live_server:
        return _step(f"See it: right-click {page} and choose **Open with Live Server**. If it's already open, it "
                     "updates by itself when you save.")
    return _step(f"See it: double-click {page} in {_files(device)} to open it in your browser, and refresh the "
                 "browser after each save.")


def try_steps(way, lang, file, folder, device=""):
    """How to try a lesson's task in the learner's setup, step by step. [] when there's nothing to add.

    The AI names the file; the code writes the steps, so they match the setup guide exactly and cost
    no tokens. "curated" follows the VS Code steps (the curated guides use VS Code), opening pages
    straight in the browser instead of with Live Server.
    """
    file = file or DEFAULT_FILES.get(lang, "practice.txt")
    if way == "alternative":
        if lang in CODEPEN_BOX:
            return [
                _step("Open CodePen, sign in, and open your Pen from **Your Work**.", "https://codepen.io", "CodePen"),
                _step(f"Put the code in the **{CODEPEN_BOX[lang]}** box. Keep what's already there unless the task "
                      "says to replace it."),
                _step("Watch the preview below update, then click **Save**."),
            ]
        if lang == "python":
            return [
                _step("Open Google Colab and your notebook.", "https://colab.research.google.com", "Google Colab"),
                _step("Click **+ Code** to add a new cell, and type the code in it."),
                _step("Click the **Run** button on the left of the cell. The result appears below it."),
            ]
        return []
    if way not in ("main", "curated") or lang not in DEFAULT_FILES:
        return []
    return [
        _step(f"Open VS Code with your project folder: **File** → **Open Recent** → `{folder}`.")
        if way == "main" else _step("Open VS Code with your project folder (**File** → **Open Recent**)."),
        _step(f"In the **Explorer** panel, click the **New File** icon and name it `{file}`. If it's already there, "
              "click it to open it."),
        _step("Type the code for the task. Typing it yourself, instead of pasting, helps you remember it."),
        _step(f"Save with {_shortcut(device, 'S')}."),
        _see_it(lang, file, device, live_server=(way == "main")),
    ]
