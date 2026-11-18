function noise(x: number, y: number) {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const easeX = fx * fx * (3 - 2 * fx);
  const easeY = fy * fy * (3 - 2 * fy);
  function hash(a: number, b: number) {
    let n = Math.imul(a, 374761393) + Math.imul(b, 668265263);
    n = Math.imul(n ^ (n >>> 13), 1274126177);
    return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
  }
  const top = hash(ix, iy) * (1 - easeX) + hash(ix + 1, iy) * easeX;
  const bottom = hash(ix, iy + 1) * (1 - easeX) + hash(ix + 1, iy + 1) * easeX;
  return top * (1 - easeY) + bottom * easeY;
}

function terrain(x: number, y: number) {
  return noise(x, y) * 0.55 + noise(x * 2.1, y * 2.1) * 0.27 + noise(x * 4.3, y * 4.3) * 0.13 + noise(x * 9.1, y * 9.1) * 0.05;
}

function makePlanet(kind: string) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 320;
  const context = canvas.getContext('2d')!;
  const image = context.createImageData(320, 320);
  const palettes: Record<string, number[][]> = {
    moon: [[53, 58, 72], [170, 173, 185]],
    copper: [[78, 43, 48], [219, 142, 103]],
    ocean: [[12, 61, 71], [105, 190, 165]],
    lavender: [[47, 44, 81], [163, 150, 192]],
    blue: [[18, 37, 77], [92, 119, 187]],
  };
  const [dark, light] = palettes[kind];
  for (let y = 0; y < 320; y++) {
    for (let x = 0; x < 320; x++) {
      const nx = (x - 159.5) / 157;
      const ny = (y - 159.5) / 157;
      const radius = nx * nx + ny * ny;
      if (radius > 1) continue;
      const nz = Math.sqrt(1 - radius);
      const longitude = Math.atan2(nx, nz);
      const latitude = Math.asin(ny);
      const ground = terrain(longitude * 6 + 32, latitude * 6 + 74);
      let texture = ground;
      if (kind === 'lavender' || kind === 'blue') {
        texture = 0.45 + Math.sin(latitude * 37 + ground * 9) * 0.13 + ground * 0.35;
      } else if (kind === 'ocean') {
        texture = Math.min(1, Math.max(0, (ground - 0.37) * 2.5));
        texture += Math.sin(latitude * 21 + ground * 14) * 0.07;
      } else if (kind === 'moon') {
        texture = ground * 0.9 + noise(longitude * 44 + 12, latitude * 44 + 4) * 0.15;
      } else {
        texture = ground * 0.8 + Math.sin(latitude * 12 + ground * 13) * 0.11;
      }
      const diffuse = Math.max(0, nx * -0.52 + ny * -0.4 + nz * 0.72);
      const illumination = 0.045 + Math.pow(diffuse, 0.9) * 1.08;
      const rim = Math.pow(1 - nz, 3.8) * Math.max(0, diffuse) * 0.4;
      const index = (y * 320 + x) * 4;
      for (let channel = 0; channel < 3; channel++) {
        const color = dark[channel] + (light[channel] - dark[channel]) * texture;
        image.data[index + channel] = Math.min(255, color * illumination + light[channel] * rim);
      }
      image.data[index + 3] = Math.min(255, (1 - radius) * 1800);
    }
  }
  context.putImageData(image, 0, 0);
  return canvas;
}
const cache: Record<string, string> = {};
export function planetImage(index: number) { const kind = ['moon', 'copper', 'ocean', 'lavender', 'blue'][index % 5]; return cache[kind] ||= makePlanet(kind).toDataURL('image/png'); }

