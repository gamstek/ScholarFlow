/** 回答卡片（简单文本渲染）。 */
export function AnswerCard({ answer }: { answer: string }) {
  if (!answer) return null;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 my-4">
      <h3 className="font-semibold text-gray-700 mb-2">回答</h3>
      <div className="text-gray-800 whitespace-pre-wrap leading-relaxed text-sm">
        {answer}
      </div>
    </div>
  );
}
