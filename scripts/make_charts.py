"""Regenerate docs/images/evals.png from results/eval-report.json."""
import json

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

with open("results/eval-report.json") as fh:
    r = json.load(fh)
pols = list(r["rca"])
vals = [r["rca"][p]["pass_at_1"] * 100 for p in pols]
fig, ax = plt.subplots(1, 2, figsize=(12, 4.2), dpi=160)
fig.patch.set_facecolor("#0b0f17")
for a in ax:
    a.set_facecolor("#0b0f17")
    a.tick_params(colors="#c9d1e0")
    for name, s in a.spines.items():
        s.set_color("#2c3a59")
        s.set_visible(name in ("left", "bottom"))
cols = ["#3ecf8e", "#7aa2ff", "#f5b84b", "#ff6b6b"]
bars = ax[0].barh(pols[::-1], vals[::-1], color=cols[::-1])
ax[0].set_xlim(0, 112)
ax[0].set_title(f"End-to-end RCA pass rate ({r['rca']['reference']['scenarios']} incidents x 3 noisy trials)",
                color="#e6ebf5", fontsize=11, loc="left")
for rect, v in zip(bars, vals[::-1], strict=False):
    ax[0].text(v + 1.5, rect.get_y() + rect.get_height() / 2, f"{v:.0f}%", va="center", color="#e6ebf5")
modes = ["bm25", "dense", "hybrid"]
k1 = [r["retrieval"][m]["recall_at_1"] * 100 for m in modes]
k3 = [r["retrieval"][m]["recall_at_3"] * 100 for m in modes]
x = np.arange(3)
ax[1].bar(x - 0.18, k1, 0.36, color="#7aa2ff", label="recall@1")
ax[1].bar(x + 0.18, k3, 0.36, color="#3ecf8e", label="recall@3")
ax[1].set_xticks(x, modes)
ax[1].set_ylim(0, 128)
ax[1].legend(frameon=False, labelcolor="#c9d1e0", loc="upper left", ncol=2)
ax[1].set_title(f"KB retrieval ({r['retrieval']['queries']} queries)", color="#e6ebf5", fontsize=11, loc="left")
for i, (a1, a3) in enumerate(zip(k1, k3, strict=False)):
    ax[1].text(i - 0.18, a1 + 2, f"{a1:.0f}", ha="center", color="#e6ebf5", fontsize=9)
    ax[1].text(i + 0.18, a3 + 2, f"{a3:.0f}", ha="center", color="#e6ebf5", fontsize=9)
plt.tight_layout()
plt.savefig("docs/images/evals.png", facecolor=fig.get_facecolor())
