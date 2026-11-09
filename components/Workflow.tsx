import { stages } from "../app/search-data";

export function Workflow({ step, loading }: { step: number; loading: boolean }) {
  return (
    <section className="workflow" aria-label="Fasi della ricerca">
      <div className="workflow-head">
        <span>IL PROCESSO</span>
        <span>Una ricerca, cinque passaggi</span>
      </div>
      <div className="steps">
        {stages.map((name, index) => (
          <div
            className={`step ${step >= index ? "step-done" : ""} ${
              step === index && loading ? "step-current" : ""
            }`}
            key={name}
          >
            <div className="step-node">
              {step > index ? "✓" : `0${index + 1}`}
            </div>
            <span>{name}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
