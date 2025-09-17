const CACHE_NAME = 'softdigootech-cache-v1';
const urlsToCache = [
  '/',
  '/static/css/bootstrap.min.css',
  '/static/style.css',
  '/static/js/chart.min.js',
  '/offline.html'
];

// 1. Evento de Instalação: Salva os arquivos essenciais no cache
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Cache aberto, adicionando URLs essenciais.');
        return cache.addAll(urlsToCache);
      })
  );
});

// 2. Evento de Ativação: Limpa os caches antigos
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cache => {
          if (cache !== CACHE_NAME) {
            console.log('Service Worker: limpando cache antigo:', cache);
            return caches.delete(cache);
          }
        })
      );
    })
  );
});

// 3. Evento de Fetch: Decide como responder a uma requisição
self.addEventListener('fetch', event => {
  // Estratégia: Network First (Tenta a rede primeiro, se falhar, usa o cache)
  // Isso é bom para páginas HTML, para sempre ter o conteúdo mais recente.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/offline.html'))
    );
    return;
  }

  // Estratégia: Cache First (Usa o cache primeiro, se falhar, busca na rede)
  // Isso é bom para arquivos estáticos que não mudam com frequência (CSS, JS, imagens).
  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      return cachedResponse || fetch(event.request);
    })
  );
});