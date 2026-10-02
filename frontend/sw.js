"use strict";

// Static shell only. News API responses and audio are deliberately never
// cached, so the app cannot present stale news as current or retain large media.
const CACHE_NAME = "dengbej-static-shell-v1";
const OFFLINE_URL = "/offline.html";
const STATIC_SHELL = [
  "/",
  "/index.html",
  "/about",
  "/about.html",
  "/contact",
  "/contact.html",
  "/privacy",
  "/privacy.html",
  "/sources",
  "/sources.html",
  "/terms",
  "/terms.html",
  "/transparency",
  "/transparency.html",
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/icons/dengbej-192.png",
  "/icons/dengbej-512.png"
];
const STATIC_ASSETS = new Set([
  "/manifest.webmanifest",
  "/icons/dengbej-192.png",
  "/icons/dengbej-512.png"
]);
const STATIC_ROUTES = new Set(STATIC_SHELL);
const AUDIO_EXTENSION = /\.(?:mp3|wav|ogg|m4a|aac)(?:$|\?)/i;

self.addEventListener("install", function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      // Cache each URL independently: one unavailable optional route must not
      // fail service-worker installation or prevent the normal website loading.
      return Promise.all(STATIC_SHELL.map(function(url) {
        return cache.add(url).catch(function() { return undefined; });
      }));
    })
  );
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(key) {
        return key !== CACHE_NAME ? caches.delete(key) : Promise.resolve(false);
      }));
    }).then(function() { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function(event) {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Never intercept cross-origin requests (current news API and S3 audio),
  // potential future same-origin /news/* APIs, or any audio request.
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/news/")) return;
  if (request.destination === "audio" || AUDIO_EXTENSION.test(url.pathname)) return;

  if (request.mode === "navigate") {
    // Network-first keeps the application shell current. Cached HTML is only an
    // offline fallback; story data still comes from the uncached news API.
    event.respondWith(
      fetch(request).then(function(response) {
        if (response.ok && STATIC_ROUTES.has(url.pathname)) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(function(cache) { cache.put(request, copy); });
        }
        return response;
      }).catch(function() {
        return caches.match(request).then(function(cached) {
          return cached || caches.match(url.pathname) || caches.match(OFFLINE_URL);
        });
      })
    );
    return;
  }

  if (STATIC_ASSETS.has(url.pathname)) {
    // Small versioned PWA metadata/icons may use cache-first behavior.
    event.respondWith(
      caches.match(request).then(function(cached) {
        return cached || fetch(request);
      })
    );
  }
});
