import { Check } from 'lucide-react';

interface StatusDotProps {
  status: 'pending' | 'active' | 'completed' | 'error';
  label: string;
}

/** 单个阶段圆点。 */
export function StatusDot({ status, label }: StatusDotProps) {
  const styles = {
    pending: 'bg-slate-100 text-slate-400 border-slate-200',
    active: 'bg-indigo-500 text-white border-indigo-500 animate-pulse',
    completed: 'bg-emerald-500 text-white border-emerald-500',
    error: 'bg-rose-500 text-white border-rose-500',
  };

  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all duration-300 ${styles[status]}`}
    >
      {status === 'completed' && <Check className="w-3 h-3" strokeWidth={2.5} />}
      {label}
    </span>
  );
}
