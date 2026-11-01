const continents = [
  [[-168,70],[-135,70],[-120,60],[-128,48],[-115,30],[-97,17],[-82,9],[-78,25],[-60,45],[-60,60],[-85,72],[-120,75]],
  [[-81,12],[-60,8],[-35,-5],[-45,-23],[-55,-38],[-67,-55],[-75,-40],[-80,-5]],
  [[-17,35],[10,37],[34,30],[42,12],[50,10],[40,-15],[27,-35],[16,-28],[8,-5],[-16,15]],
  [[-10,36],[-9,55],[10,70],[35,70],[50,60],[80,73],[125,72],[170,60],[155,45],[140,38],[125,20],[110,2],[95,7],[80,8],[70,24],[50,28],[35,42],[25,40]],
  [[113,-22],[130,-12],[145,-15],[153,-30],[137,-39],[115,-34]],
  [[-52,59],[-42,62],[-20,80],[-45,84],[-60,73]],
  [[47,-13],[50,-16],[47,-26],[43,-20]],
  [[130,32],[142,45],[145,40],[135,33]],
];

export function animateGlobe(canvas) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  let frame = 0;
  let visible = true;
  new IntersectionObserver(entries => { visible = entries[0].isIntersecting; }).observe(canvas);
  function draw(t) {
    if (visible) {
      const size = Math.max(220, canvas.clientWidth);
      const ratio = Math.min(devicePixelRatio || 1, 2);
      if (canvas.width !== size * ratio) { canvas.width = size * ratio; canvas.height = size * ratio; }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, size, size);
      const r = size * 0.42, c = size / 2, rotation = reduce.matches ? -0.8 : t / 42000 - 0.8;
      const project = (lon, lat) => {
        const l = lon * Math.PI / 180 + rotation, a = lat * Math.PI / 180;
        return [c + r * Math.cos(a) * Math.sin(l), c - r * Math.sin(a), Math.cos(a) * Math.cos(l)];
      };
      const gradient = ctx.createRadialGradient(c - r / 3, c - r / 3, 0, c, c, r);
      gradient.addColorStop(0, "#f0f5ff"); gradient.addColorStop(1, "#d3e2fa");
      ctx.fillStyle = gradient; ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.fill();
      const line = points => {
        ctx.beginPath(); let started = false;
        for (const [lon, lat] of points) {
          const [x, y, z] = project(lon, lat);
          if (z > 0) { if (!started) ctx.moveTo(x, y); else ctx.lineTo(x, y); started = true; }
          else started = false;
        }
        ctx.stroke();
      };
      ctx.strokeStyle = "#1a73e825"; ctx.lineWidth = 0.6;
      for (let lat = -60; lat <= 60; lat += 20) line(Array.from({length:181}, (_,i) => [-180 + i * 2, lat]));
      for (let lon = -180; lon < 180; lon += 20) line(Array.from({length:91}, (_,i) => [lon, -90 + i * 2]));
      ctx.strokeStyle = "#5989c4b0"; ctx.lineWidth = 1;
      for (const polygon of continents) {
        const dense = [];
        for (let i = 0; i < polygon.length; i++) {
          const a = polygon[i], b = polygon[(i + 1) % polygon.length];
          for (let j = 0; j < 10; j++) dense.push([a[0] + (b[0] - a[0]) * j / 10, a[1] + (b[1] - a[1]) * j / 10]);
        }
        line(dense);
      }
      ctx.strokeStyle = "#6692c960";ctx.beginPath();ctx.arc(c,c,r,0,Math.PI*2);ctx.stroke();
      for (const point of [[116,40],[-74,41],[2,49],[139,36],[103,1]]) {
        const [x,y,z] = project(...point);
        if (z > 0) {
          ctx.fillStyle = "#1a73e8";ctx.beginPath();ctx.arc(x,y,2.2,0,Math.PI*2);ctx.fill();
          ctx.strokeStyle = "#1a73e830";ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.stroke();
        }
      }
    }
    if (!reduce.matches) frame = requestAnimationFrame(draw);
  }
  draw(0);
  reduce.addEventListener("change", () => { cancelAnimationFrame(frame); draw(performance.now()); });
}
