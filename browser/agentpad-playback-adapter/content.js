(() => {
  const STEP = 0.25;
  const MIN = 0.25;
  const MAX = 3.0;
  let toastTimer;

  function showRate(video) {
    let toast = document.getElementById("agentpad-playback-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "agentpad-playback-toast";
      Object.assign(toast.style, {
        position: "fixed", left: "50%", top: "18%", zIndex: "2147483647",
        transform: "translateX(-50%)", padding: "9px 15px", borderRadius: "8px",
        color: "white", background: "rgba(0,0,0,.78)", font: "600 16px sans-serif",
        pointerEvents: "none"
      });
      document.documentElement.appendChild(toast);
    }
    toast.textContent = `Agentpad · ${video.playbackRate.toFixed(2)}×`;
    toast.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.style.display = "none"; }, 900);
  }

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (event.key !== "[" && event.key !== "]") return;
    if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
    const video = document.querySelector("video");
    if (!video) return;
    const next = Math.max(MIN, Math.min(MAX,
      video.playbackRate + (event.key === "]" ? STEP : -STEP)));
    video.playbackRate = Number(next.toFixed(2));
    event.preventDefault();
    event.stopPropagation();
    showRate(video);
  }, true);
})();
