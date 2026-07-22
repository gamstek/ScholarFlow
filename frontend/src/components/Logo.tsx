/**
 * ScholarFlow-Bio Logo — SVG 组件。
 *
 * 设计：DNA 双螺旋 + "ScholarFlow" 文字 + "-Bio" 下标。
 * 颜色：indigo-600（学术蓝）+ emerald-500（生物绿）。
 */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2 select-none">
      {/* DNA 图标 */}
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="shrink-0"
      >
        {/* 左链 */}
        <path
          d="M10 4 C10 10 12 14 16 16 C20 18 22 22 22 28"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          className="text-indigo-500"
        />
        {/* 右链 */}
        <path
          d="M22 4 C22 10 20 14 16 16 C12 18 10 22 10 28"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          className="text-emerald-400"
        />
        {/* 横桥（上） */}
        <line x1="12.5" y1="9" x2="19.5" y2="9"
          stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
          className="text-indigo-300"
        />
        {/* 横桥（中） */}
        <line x1="14" y1="16" x2="18" y2="16"
          stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
          className="text-emerald-300"
        />
        {/* 横桥（下） */}
        <line x1="12.5" y1="23" x2="19.5" y2="23"
          stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
          className="text-indigo-300"
        />
      </svg>

      {/* 文字 */}
      <div className="leading-none">
        <span className="text-base font-bold text-indigo-600 tracking-tight">
          ScholarFlow
        </span>
        <span className="text-[11px] font-semibold text-emerald-500 ml-0.5">
          Bio
        </span>
      </div>
    </div>
  );
}
