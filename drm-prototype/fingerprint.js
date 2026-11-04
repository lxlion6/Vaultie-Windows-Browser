module.exports=function fingerprint(sessionSeed){
  "use strict";
  const scheme = location.protocol;
  if (scheme !== "https:" && scheme !== "http:") return;
  // Do not tamper with authentication or DRM-sensitive Amazon/Prime scripts.
  const host = location.hostname.toLowerCase();
  if (host === "primevideo.com" || host.endsWith(".primevideo.com") ||
      host === "amazon.com" || host.endsWith(".amazon.com") ||
      host === "amazon.de" || host.endsWith(".amazon.de") ||
      host === "amazon.co.uk" || host.endsWith(".amazon.co.uk")) return;
  // A fresh random seed per browser session; isolate observations by site.
  let state = 2166136261;
  const seed = sessionSeed + "|" + location.hostname.toLowerCase();
  for (let i = 0; i < seed.length; i++) {
    state ^= seed.charCodeAt(i);
    state = Math.imul(state, 16777619) >>> 0;
  }
  const offset = state >>> 0;
  const descriptor = (obj, key, value) => {
    try {
      if (!obj) return;
      Object.defineProperty(obj, key, {
        configurable: true, enumerable: true, get: () => value
      });
    } catch (_) {}
  };
  // Generalize hardware characteristics; do not remove functional APIs.
  descriptor(Navigator.prototype, "hardwareConcurrency", 4);
  descriptor(Navigator.prototype, "deviceMemory", 4);
  // Hide high-entropy GPU and driver details while preserving WebGL.
  for (const name of ["WebGLRenderingContext", "WebGL2RenderingContext"]) {
    const cls = window[name];
    if (!cls || !cls.prototype || !cls.prototype.getParameter) continue;
    const nativeGet = cls.prototype.getParameter;
    cls.prototype.getParameter = function(parameter) {
      if (parameter === 0x9245) return "WebKit";
      if (parameter === 0x9246) return "WebKit WebGL";
      return nativeGet.call(this, parameter);
    };
  }
  // Stable, tiny change per origin+session only for canvas readback.
  // Do not mutate the visible canvas or repeatedly redraw it.
  const pixelNoise = (data, width, height) => {
    if (!width || !height || !data || data.length < 4) return;
    const pixel = (offset % (width * height)) * 4;
    if (data[pixel + 3] > 0) {
      data[pixel + (offset % 3)] ^= 1;
    }
  };
  const originalRead = window.CanvasRenderingContext2D &&
    CanvasRenderingContext2D.prototype.getImageData;
  if (window.CanvasRenderingContext2D) {
    const proto = CanvasRenderingContext2D.prototype;
    const nativeImage = originalRead;
    if (nativeImage) proto.getImageData = function(...args) {
      const result = nativeImage.apply(this, args);
      try { pixelNoise(result.data, result.width, result.height); } catch (_) {}
      return result;
    };
  }
  if (window.HTMLCanvasElement) {
    const proto = HTMLCanvasElement.prototype;
    const nativeURL = proto.toDataURL;
    if (nativeURL) proto.toDataURL = function(...args) {
      try {
        if (this.width > 0 && this.height > 0 &&
            this.width * this.height <= 4000000 &&
            this.getContext("2d")) {
          const clone = document.createElement("canvas");
          clone.width = this.width;
          clone.height = this.height;
          const context = clone.getContext("2d");
          // Browser-internal original read avoids double modification.
          context.drawImage(this, 0, 0);
          const image = originalRead.call(context, 0, 0, clone.width, clone.height);
          pixelNoise(image.data, image.width, image.height);
          context.putImageData(image, 0, 0);
          return nativeURL.apply(clone, args);
        }
      } catch (_) {}
      return nativeURL.apply(this, args);
    };
  }
};
