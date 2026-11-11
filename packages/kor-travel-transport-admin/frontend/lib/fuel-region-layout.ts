type RegionCardRect = { left: number; top: number; width: number; height: number };
// 좌표는 변경하지 않고 화면에서만 카드를 옮긴다. 카드마다 최대 129곳만 검사해 시군구 수에도 비용을 제한한다.
export function layoutFuelRegionCards(cards: RegionCardRect[], width: number, height: number, reserved: RegionCardRect[] = []) {
  const gap = 8;
  const occupied = [...reserved];
  const overlaps = (a: RegionCardRect, b: RegionCardRect) => a.left < b.left + b.width + gap
    && a.left + a.width + gap > b.left && a.top < b.top + b.height + gap && a.top + a.height + gap > b.top;
  return cards.map(card => {
    const candidates: RegionCardRect[] = [];
    if (card.width <= width - gap * 2 && card.height <= height - gap * 2) {
      candidates.push({ ...card,
        left: Math.max(gap, Math.min(width - card.width - gap, card.left)),
        top: Math.max(gap, Math.min(height - card.height - gap, card.top)),
      });
      for (let top = gap; top <= height - card.height - gap && candidates.length < 129; top += card.height + gap)
        for (let left = gap; left <= width - card.width - gap && candidates.length < 129; left += card.width + gap)
          candidates.push({ ...card, left, top });
      candidates.sort((a, b) => Math.hypot(a.left - card.left, a.top - card.top) - Math.hypot(b.left - card.left, b.top - card.top));
    }
    const placed = candidates.find(candidate => !occupied.some(other => overlaps(candidate, other)));
    if (placed) occupied.push(placed);
    return { x: placed ? placed.left - card.left : 0, y: placed ? placed.top - card.top : 0, placed: Boolean(placed) };
  });
}

