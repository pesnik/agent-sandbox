(() => {
  // Hide navigator.webdriver — the primary bot detection signal
  Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
  });

  // Spoof plugins (empty array is a headless giveaway)
  Object.defineProperty(navigator, 'plugins', {
    get: () => {
      const arr = [1, 2, 3, 4, 5];
      arr.item = (i) => arr[i];
      arr.namedItem = () => null;
      arr.refresh = () => {};
      return arr;
    },
    configurable: true,
  });

  // Spoof mimeTypes
  Object.defineProperty(navigator, 'mimeTypes', {
    get: () => {
      const arr = [];
      arr.item = () => null;
      arr.namedItem = () => null;
      return arr;
    },
    configurable: true,
  });

  // Languages
  Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
  });

  // Fix Permissions.query — headless returns 'denied' for notifications
  if (window.Permissions && window.Permissions.prototype) {
    const orig = window.Permissions.prototype.query;
    window.Permissions.prototype.query = function(params) {
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: 'default', onchange: null });
      }
      return orig.apply(this, arguments);
    };
  }

  // Remove CDP-injected globals
  delete window.__playwright;
  delete window.__pw_manual;
  delete window.__selenium_evaluate;
  delete window.__webdriver_evaluate;
  delete window.__driver_evaluate;
  delete window.__webdriverFunc;

  // Ensure chrome runtime looks normal
  if (!window.chrome) {
    window.chrome = {};
  }
  if (!window.chrome.runtime) {
    window.chrome.runtime = {
      connect: () => {},
      sendMessage: () => {},
      onMessage: { addListener: () => {} },
    };
  }
})();
