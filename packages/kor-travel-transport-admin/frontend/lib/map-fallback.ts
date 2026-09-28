// MapLibre의 raster 디코더는 SVG를 지원하지 않는다. 외부 요청 없이 읽는 1px 회색 PNG다.
// 타일 실패 안내는 지도 위의 접근 가능한 상태 메시지로 별도 표시한다.
export const MAP_FALLBACK_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4+vXrfwAJoQPf1gvoUgAAAABJRU5ErkJggg==";
