export default function Tile({ label, value, note, tone }: {
  label: string; value: string; note?: string; tone?: "good" | "bad";
}) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}
