/** 빈 값·자리표시자 키는 라이브러리에 빈 문자열로 넘겨 `missing-api-key` 대체 화면을 쓰게 한다. */
export function vworldApiKey(value: string | undefined): string {
  const trimmed = value?.trim() ?? "";
  return trimmed === "CHANGE_ME" || trimmed.startsWith("replace-with-") ? "" : trimmed;
}

/** 로그에 남기기 전에 메시지 안의 VWorld 키를 가린다(라이브러리 `redactVWorldUrl`은 URL 하나만 가린다). */
export function redactVWorldText(value: string | undefined): string | undefined {
  return value?.replace(/(\/req\/wmts\/1\.0\.0\/)([^/?#\s]+)(\/)/g, "$1***$3");
}
