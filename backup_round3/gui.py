"""Desktop GUI.

    python gui.py
"""
import queue
import threading
import tkinter as tk
from tkinter import ttk

COLORS = {
    "neutral": {"background": "#f4f4f5", "accent": "#52525b"},
    "injection": {"background": "#fde8e8", "accent": "#b42318"},
    "benign": {"background": "#e6f4ea", "accent": "#1e7a3c"},
}
RULE_LABELS = {
    "imperative_verb_density": "Command verbs",
    "override_phrase_count": "Override phrases",
    "role_reassignment_score": "Role reassignment",
    "delimiter_mimicry_count": "Fake system markers",
    "log_text_length": "Text length (log)",
    "special_char_ratio": "Special characters",
    "authority_claim_count": "Authority claims",
    "indirect_address_count": "Addresses the AI from inside content",
    "exfiltration_count": "Asks for hidden prompt or secrets",
    "output_manipulation_count": "Controls the output",
    "hypothetical_framing_count": "Hypothetical or no-limits framing",
    "urgency_pressure_count": "Urgency or pressure",
    "second_person_command_ratio": "Commands aimed at 'you'",
    "obfuscation_score": "Obfuscation",
    "payload_split_count": "Split payload",
    "uppercase_ratio": "Uppercase letters",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Prompt Injection Detector")
        self.geometry("860x720")
        self.minsize(680, 560)

        self.header = tk.Frame(self, padx=16, pady=12)
        self.header.pack(fill="x")
        self.verdict = tk.Label(self.header, text="Enter text and press Check text",
                                font=("TkDefaultFont", 16, "bold"), anchor="w")
        self.verdict.pack(fill="x")
        self.detail = tk.Label(self.header, text="", anchor="w", justify="left")
        self.detail.pack(fill="x")

        body = tk.Frame(self, padx=16, pady=8)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Text to check", anchor="w").pack(fill="x")
        self.input = tk.Text(body, height=10, wrap="word", undo=True)
        self.input.pack(fill="both", expand=True)
        self.input.bind("<Control-Return>", lambda event: self.check())

        buttons = tk.Frame(body, pady=8)
        buttons.pack(fill="x")
        self.check_button = ttk.Button(buttons, text="Check text", command=self.check)
        self.check_button.pack(side="left")
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left", padx=8)
        self.status = tk.Label(buttons, text="Ctrl+Enter also runs the check", anchor="e")
        self.status.pack(side="right")

        tk.Label(body, text="Features", anchor="w").pack(fill="x")
        table = tk.Frame(body)
        table.pack(fill="both", expand=True)
        self.features = ttk.Treeview(
            table, columns=("fired", "value", "matches"), show="tree headings", height=16)
        self.features.heading("#0", text="Rule")
        self.features.heading("fired", text="Fired")
        self.features.heading("value", text="Value")
        self.features.heading("matches", text="Matched text")
        self.features.column("#0", width=270, stretch=False)
        self.features.column("fired", width=60, anchor="center", stretch=False)
        self.features.column("value", width=80, anchor="e", stretch=False)
        self.features.column("matches", width=400)
        self.features.tag_configure("fired", foreground=COLORS["injection"]["accent"])
        self.features.tag_configure("quiet", foreground="#71717a")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.features.yview)
        self.features.configure(yscrollcommand=scrollbar.set)
        self.features.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.results = queue.Queue()
        self.tint("neutral")
        self.input.focus_set()

    def tint(self, state):
        colors = COLORS[state]
        for widget in (self.header, self.verdict, self.detail):
            widget.configure(background=colors["background"])
        self.verdict.configure(foreground=colors["accent"])
        self.input.configure(background="#ffffff" if state == "neutral" else colors["background"])

    def clear(self):
        self.input.delete("1.0", "end")
        self.features.delete(*self.features.get_children())
        self.verdict.configure(text="Enter text and press Check text")
        self.detail.configure(text="")
        self.status.configure(text="Ctrl+Enter also runs the check")
        self.tint("neutral")
        self.input.focus_set()

    def check(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            self.status.configure(text="Enter some text first")
            return "break"
        self.check_button.state(["disabled"])
        self.status.configure(text="Checking... (the first check loads the model)")
        threading.Thread(target=self.run_prediction, args=(text,), daemon=True).start()
        self.after(100, self.collect)
        return "break"

    def run_prediction(self, text):
        # same function the CLI uses; runs off the UI thread so the window stays responsive
        try:
            from src.predict import predict
            self.results.put((predict(text), None))
        except Exception as problem:
            self.results.put((None, str(problem)))

    def collect(self):
        # tkinter may only be touched from the main thread, so the result is picked up here
        try:
            result, error = self.results.get_nowait()
        except queue.Empty:
            self.after(100, self.collect)
            return
        self.show(result, error)

    def show(self, result, error):
        self.check_button.state(["!disabled"])
        if error:
            self.status.configure(text="")
            self.verdict.configure(text="Could not check the text")
            self.detail.configure(text=error)
            self.tint("neutral")
            return

        self.status.configure(text="")
        self.tint(result["verdict"])
        self.verdict.configure(text=f"{result['verdict'].upper()}  ·  "
                                    f"{result['confidence']:.0%} confidence")
        detail = f"Injection probability {result['probability']:.0%}"
        if result["semantic_only"]:
            detail += "\nNo rule fired: flagged by meaning (semantic match from the embedding)"
        if result["segment"]:
            part = " ".join(result["segment"].split())
            detail += (f"\nMost suspicious of {result['windows']} parts: "
                       f"{part[:160]}{'...' if len(part) > 160 else ''}")
        self.detail.configure(text=detail, wraplength=self.winfo_width() - 40)

        self.features.delete(*self.features.get_children())
        ordered = sorted(result["features"], key=lambda name: name not in result["fired"])
        for name in ordered:
            hit = result["fired"].get(name)
            descriptive = name in result["descriptive"]
            self.features.insert(
                "", "end", text=RULE_LABELS.get(name, name),
                values=("yes" if hit else ("-" if descriptive else "no"),
                        f"{result['features'][name]:.3g}",
                        "; ".join(hit["matches"][:3]) if hit else ""),
                tags=("fired" if hit else "quiet",),
            )


if __name__ == "__main__":
    App().mainloop()
