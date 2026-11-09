import json, time, statistics as st, sys
from maia2 import model as m2, inference
from maia_bench import fens
dev = sys.argv[1]
t = time.perf_counter(); mdl = m2.from_pretrained(type="rapid", device=dev); load = time.perf_counter() - t
prep = inference.prepare()
fs = fens(200)
for f in fs[:5]: inference.inference_each(mdl, prep, f, 1500, 1500)
lat = []
for f in fs:
    s = time.perf_counter(); probs, win = inference.inference_each(mdl, prep, f, 1500, 1500); lat.append((time.perf_counter()-s)*1000)
print(json.dumps({"model": "maia2-rapid", "device": dev, "load_s": round(load, 2), "b1_p50_ms": round(st.median(lat), 2),
                  "b1_p95_ms": round(sorted(lat)[int(.95*len(lat))], 2), "sample_win_prob": round(float(win), 3)}))
