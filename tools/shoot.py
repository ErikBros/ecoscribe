"""Screenshot the window pages in headless Edge (demo API) for design review.

    python shoot.py [out_dir]   -> <page>@<scale>x.png for every page at 100% and 150%
Headless Edge opens no visible window. tools/before_after.py uses SHOTS and shot() too.
"""
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SHOTS = {
    "inicio": "page=inicio", "historial": "page=historial", "ajustes": "page=ajustes",
    "bienvenida": "page=bienvenida&welcome=1",
    **{f"setup-{k}": f"page=bienvenida&welcome=1&sstep={k}{q}" for k, q in
       (("permissions", "&mac=1"), ("models", ""), ("mic", ""), ("shortcut", ""), ("try", ""), ("done", ""))},
    "inicio-version": "page=inicio&update=1",
    "detenido": "page=inicio&state=stopped",
    "cargando": "page=inicio&state=loading",
    "gpu-descarga": "page=inicio&gpurt=downloading", "gpu-fallo": "page=inicio&gpurt=failed",  # dictado-7e1
    "ajustes-cambios": "page=ajustes&dirty=1",
    "reuniones": "page=reuniones", "reuniones-vacia": "page=reuniones&rec=0",
    "reunion-directo": "page=reuniones/2026-10-05_1400_retro",
    "reunion-lista": "page=reuniones/2026-10-05_0915_planering",
    "reunion-cola": "page=reuniones/2026-10-05_1130_podcast",
    "reunion-resumiendo": "page=reuniones/2026-10-04_1600_kund",
    "reunion-reemplazar": "page=reuniones/2026-10-04_1600_kund&replace=1",  # the Replace list offered (dictado-9lo)
    "reunion-reemplazado": "page=reuniones/2026-10-04_1600_kund&replace=1&replaced=1",  # ... and applied, with Undo
    "reunion-sin-invitados": "page=reuniones/2026-10-05_0915_planering&noguests=1&email=1",  # Email participants, no invite (dictado-qxr)
    "historial-editar": "page=historial&hedit=1", "historial-aprender": "page=historial&learn=1",
    "insights": "page=insights&insights=1",
}
TALL = {"inicio-largo": "page=inicio", "ajustes-largo": "page=ajustes&dirty=1", "ajustes-frases": "page=ajustes&sc=1", "insights-largo": "page=insights&insights=1"}


def shot(web: Path, query: str, out: Path, size=(980, 690), scale=1.0) -> Path:
    """One page of the window in `web` (a folder with index.html) as a PNG."""
    index = (Path(web) / "index.html").as_uri()
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--force-device-scale-factor={scale}", f"--window-size={size[0]},{size[1]}",
                    "--virtual-time-budget=2500", f"--screenshot={out}", f"{index}?demo=1&{query}"],
                   check=True, capture_output=True, timeout=60)
    return out


if __name__ == "__main__":
    OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else APP / "packaging" / "shots"
    OUT.mkdir(parents=True, exist_ok=True)
    web = APP / "ecoscribe" / "web"
    for scale in (1, 1.5):
        for name, q in SHOTS.items():
            print(shot(web, q, OUT / f"{name}@{scale}x.png", scale=scale).name)
    for name, q in TALL.items():
        print(shot(web, q, OUT / f"{name}@1x.png", size=(980, 1180)).name)
