import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

/**
 * One topic of the in-app usage guide: a stable anchor id, a heading key, a
 * short lead and an ordered list of steps. Every string is resolved through the
 * i18n catalogue — this component owns no user-visible literals.
 */
interface GuideTopic {
  id: string;
  titleKey: MessageKey;
  leadKey: MessageKey;
  stepKeys: MessageKey[];
}

/**
 * The five guide topics, in reading order. Installation is intentionally NOT a
 * topic: the Owner scoped the guide to in-app usage (first steps, world import,
 * tool workshop, bug report and updates).
 */
const GUIDE_TOPICS: GuideTopic[] = [
  {
    id: "first-steps",
    titleKey: "profile.guide.firstSteps.title",
    leadKey: "profile.guide.firstSteps.lead",
    stepKeys: [
      "profile.guide.firstSteps.step1",
      "profile.guide.firstSteps.step2",
      "profile.guide.firstSteps.step3",
      "profile.guide.firstSteps.step4",
    ],
  },
  {
    id: "import",
    titleKey: "profile.guide.import.title",
    leadKey: "profile.guide.import.lead",
    stepKeys: [
      "profile.guide.import.step1",
      "profile.guide.import.step2",
      "profile.guide.import.step3",
      "profile.guide.import.step4",
    ],
  },
  {
    id: "workshop",
    titleKey: "profile.guide.workshop.title",
    leadKey: "profile.guide.workshop.lead",
    stepKeys: [
      "profile.guide.workshop.step1",
      "profile.guide.workshop.step2",
      "profile.guide.workshop.step3",
    ],
  },
  {
    id: "report",
    titleKey: "profile.guide.report.title",
    leadKey: "profile.guide.report.lead",
    stepKeys: [
      "profile.guide.report.step1",
      "profile.guide.report.step2",
      "profile.guide.report.step3",
      "profile.guide.report.step4",
    ],
  },
  {
    id: "updates",
    titleKey: "profile.guide.updates.title",
    leadKey: "profile.guide.updates.lead",
    stepKeys: [
      "profile.guide.updates.step1",
      "profile.guide.updates.step2",
      "profile.guide.updates.step3",
      "profile.guide.updates.step4",
    ],
  },
];

/**
 * Perfil → Guía de uso — the in-app usage guide, rendered entirely from the i18n
 * catalogue (no markdown, no build step, no backend). A short intro is followed
 * by one accessible block per topic: an h4 heading, a lead line and an ordered
 * list of steps. Heading levels stay contiguous under the page panel h2
 * (h3 section title → h4 topic titles), mirroring the other Profile sections.
 */
export function UsageGuideSection() {
  const { t } = useAppLanguage();

  return (
    <section
      aria-labelledby="profile-guide-panel-title"
      className="rounded-lg border border-edge bg-surface-raised p-4"
    >
      <h3
        id="profile-guide-panel-title"
        className="font-heading text-body text-primary"
      >
        {t("profile.guide.panelTitle")}
      </h3>
      <p className="mt-1 text-small text-muted">{t("profile.guide.intro")}</p>

      <div className="mt-4 flex flex-col gap-4">
        {GUIDE_TOPICS.map((topic) => (
          <article
            key={topic.id}
            aria-labelledby={`profile-guide-topic-${topic.id}`}
            className="rounded-lg border border-edge bg-surface p-3"
          >
            <h4
              id={`profile-guide-topic-${topic.id}`}
              className="font-heading text-body text-primary"
            >
              {t(topic.titleKey)}
            </h4>
            <p className="mt-1 text-small text-muted">{t(topic.leadKey)}</p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-small text-primary">
              {topic.stepKeys.map((key) => (
                <li key={key}>{t(key)}</li>
              ))}
            </ol>
          </article>
        ))}
      </div>
    </section>
  );
}
