export type FuelBrand = { code: string; name: string; image: string | null };

// 제공기관의 상표 코드가 있으면 이름보다 우선한다. 자가상표를 정유사로 추측하지 않는다.
const brands: Record<string, FuelBrand> = {
  SKE: { code: "SKE", name: "SK에너지", image: "sk.gif" },
  GSC: { code: "GSC", name: "GS칼텍스", image: "gs.gif" },
  HDO: { code: "HDO", name: "HD현대오일뱅크", image: "hy.gif" },
  SOL: { code: "SOL", name: "S-OIL", image: "soil.gif" },
  SKG: { code: "SKG", name: "SK가스", image: "sk_gas.gif" },
  E1G: { code: "E1G", name: "E1", image: "e1.gif" },
  NCO: { code: "NCO", name: "남해화학클린오일", image: "nc.gif" },
  NHO: { code: "NHO", name: "농협알뜰 (NH-OIL)", image: "nho.gif" },
  RTO: { code: "RTO", name: "알뜰주유소", image: "rto.gif" },
  RTE: { code: "RTE", name: "자영알뜰", image: "rto.gif" },
  RTX: { code: "RTX", name: "고속도로알뜰 (EX-OIL)", image: "rtx.gif" },
  ETC: { code: "ETC", name: "자가상표", image: null },
};
const normalize = (value: string) => value.toUpperCase().replace(/[\s\-·]/g, "");
const aliases: Record<string, string> = {
  SK에너지: "SKE", SKENERGY: "SKE", GS칼텍스: "GSC", GSCALTEX: "GSC",
  현대오일뱅크: "HDO", HD현대오일뱅크: "HDO", HYUNDAIOILBANK: "HDO", HDHYUNDAIOILBANK: "HDO",
  SOIL: "SOL", 에쓰오일: "SOL", 에스오일: "SOL", SK가스: "SKG", SKGAS: "SKG", E1: "E1G",
  남해화학클린오일: "NCO", NHOIL: "NHO", 농협알뜰: "NHO", 알뜰주유소: "RTO", 알뜰: "RTO", 자영알뜰: "RTE", 고속도로알뜰: "RTX", EXOIL: "RTX", 자가상표: "ETC",
};
export function fuelBrand(code?: string | null, name?: string | null): FuelBrand {
  const key = code?.trim().toUpperCase();
  if (key) return brands[key] ?? { code: key, name: name?.trim() || "상표 미확인", image: null };
  const alias = name ? aliases[normalize(name)] : null;
  return alias ? brands[alias] : { code: "", name: name?.trim() || "상표 미제공", image: null };
}
