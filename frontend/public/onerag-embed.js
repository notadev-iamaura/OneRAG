/**
 * OneRAG 임베드 host loader (한 줄 설치용 스크립트).
 *
 * 외부 웹사이트에 아래처럼 <script>를 삽입하면 sandbox iframe으로 챗봇이 임베드된다.
 *
 *   <script
 *     src="https://your-onerag-host/onerag-embed.js"
 *     data-onerag-embed
 *     data-base-url="https://your-onerag-host"
 *     data-target="#chat-container"
 *     data-height="640px"></script>
 *
 * 보안:
 *   - iframe은 sandbox 속성으로 격리된다(기본: allow-scripts allow-forms allow-same-origin allow-popups).
 *   - 부모는 iframe의 targetOrigin으로만 메시지를 전송하고, 수신 메시지의 origin/source를 검증한다.
 *
 * 동작:
 *   - iframe이 /embed/chat 라우트를 로드하면 onerag:ready/onerag:resize 이벤트로 높이를 보고하고,
 *     loader가 이를 받아 iframe 높이를 자동 조정한다.
 *   - window.OneRAGEmbed.last.send/focus/stop/ping API로 부모에서 챗봇을 제어할 수 있다.
 */
(function () {
  'use strict';

  // 스크립트 식별 속성
  var SCRIPT_ATTR = 'data-onerag-embed';
  var DEFAULT_HEIGHT = '720px';
  var READY_EVENT = 'onerag:ready';
  var RESIZE_EVENT = 'onerag:resize';

  // 현재 실행 중인 <script> 요소를 찾는다.
  function currentScript() {
    return document.currentScript || document.querySelector('script[' + SCRIPT_ATTR + ']');
  }

  // data-* 속성을 읽되, 비어 있으면 fallback을 반환한다.
  function attr(script, name, fallback) {
    if (!script) return fallback;
    var value = script.getAttribute(name);
    return value == null || value === '' ? fallback : value;
  }

  // iframe이 로드할 /embed/chat URL을 결정한다.
  // 우선순위: data-src > data-base-url > 스크립트 src origin > 현재 페이지 origin
  function resolveSrc(script) {
    var explicitSrc = attr(script, 'data-src', '');
    if (explicitSrc) return explicitSrc;

    var baseUrl = attr(script, 'data-base-url', '');
    if (!baseUrl && script && script.src) {
      baseUrl = new URL(script.src, window.location.href).origin;
    }
    if (!baseUrl) {
      baseUrl = window.location.origin;
    }
    return new URL('/embed/chat', baseUrl).toString();
  }

  // postMessage 대상 origin을 결정한다(iframe src의 origin).
  function targetOriginFor(src, script) {
    var explicit = attr(script, 'data-target-origin', '');
    if (explicit) return explicit;
    return new URL(src, window.location.href).origin;
  }

  // iframe을 삽입할 DOM 위치를 결정한다.
  function mountTarget(script) {
    var selector = attr(script, 'data-target', '');
    if (selector) {
      return document.querySelector(selector);
    }
    return script && script.parentElement ? script.parentElement : document.body;
  }

  // sandbox 격리된 iframe을 생성한다.
  function createIframe(script, src) {
    var iframe = document.createElement('iframe');
    iframe.src = src;
    iframe.title = attr(script, 'data-title', 'OneRAG chat');
    iframe.loading = attr(script, 'data-loading', 'lazy');
    iframe.referrerPolicy = attr(script, 'data-referrer-policy', 'strict-origin-when-cross-origin');
    iframe.allow = attr(script, 'data-allow', '');
    iframe.style.width = attr(script, 'data-width', '100%');
    iframe.style.height = attr(script, 'data-height', DEFAULT_HEIGHT);
    iframe.style.border = '0';
    iframe.style.display = 'block';
    // 핵심 보안: sandbox 속성으로 iframe 권한을 제한한다.
    iframe.setAttribute(
      'sandbox',
      attr(script, 'data-sandbox', 'allow-scripts allow-forms allow-same-origin allow-popups')
    );
    return iframe;
  }

  // iframe 생성 + 부모↔iframe 메시지 브리지 구성.
  function createEmbed(script) {
    var src = resolveSrc(script);
    var targetOrigin = targetOriginFor(src, script);
    var iframe = createIframe(script, src);
    var target = mountTarget(script);
    target.appendChild(iframe);

    // iframe으로 host 메시지를 전송한다(targetOrigin 명시).
    function post(type, extra) {
      if (!iframe.contentWindow) return;
      iframe.contentWindow.postMessage(Object.assign({
        source: 'onerag-host',
        type: type
      }, extra || {}), targetOrigin);
    }

    // iframe이 보낸 ready/resize 이벤트를 받아 높이를 자동 조정한다.
    function onMessage(event) {
      // origin/source 검증
      if (event.origin !== targetOrigin) return;
      var data = event.data || {};
      if (data.source !== 'onerag-embed') return;
      if (data.type === READY_EVENT || data.type === RESIZE_EVENT) {
        if (typeof data.height === 'number' && data.height > 0) {
          iframe.style.height = Math.ceil(data.height) + 'px';
        }
      }
    }

    window.addEventListener('message', onMessage);

    // 부모 페이지에서 챗봇을 제어할 수 있는 공개 API.
    return {
      iframe: iframe,
      send: function (message, requestId) {
        post('onerag:send', { message: message, requestId: requestId });
      },
      focus: function (requestId) {
        post('onerag:focus', { requestId: requestId });
      },
      stop: function (requestId) {
        post('onerag:stop', { requestId: requestId });
      },
      ping: function (requestId) {
        post('onerag:ping', { requestId: requestId });
      },
      destroy: function () {
        window.removeEventListener('message', onMessage);
        iframe.remove();
      }
    };
  }

  var script = currentScript();
  var api = createEmbed(script);
  // 전역에 인스턴스를 등록(다중 임베드 지원).
  window.OneRAGEmbed = window.OneRAGEmbed || { instances: [] };
  window.OneRAGEmbed.instances.push(api);
  window.OneRAGEmbed.last = api;
})();
