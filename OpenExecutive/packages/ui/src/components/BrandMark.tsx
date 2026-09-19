type BrandMarkSize = "sm" | "md" | "lg";

const BOX_CLASSES: Record<BrandMarkSize, string> = {
  sm: "w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20",
  md: "w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20",
  lg: "w-12 h-12 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-xl shadow-indigo-500/25",
};

const TEXT_CLASSES: Record<BrandMarkSize, string> = {
  sm: "text-white text-[10px] tracking-tight font-bold",
  md: "text-white text-[10px] tracking-tight font-semibold",
  lg: "text-white text-base tracking-tight font-bold",
};

interface BrandMarkProps {
  size?: BrandMarkSize;
}

export default function BrandMark({ size = "sm" }: BrandMarkProps) {
  return (
    <div className={BOX_CLASSES[size]} aria-hidden>
      <span className={TEXT_CLASSES[size]}>OE</span>
    </div>
  );
}
