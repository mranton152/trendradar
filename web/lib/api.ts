import mockTrends from "../mocks/trends.json";
import mockTrends2021 from "../mocks/trends-2021.json";

export type Trend = {
  trend_id: string;
  rank: number;
  title: string;
  label_en: string;
  aliases: string[];
  emergence_score: number;
  components: {
    novelty: number;
    growth: number;
    accel: number;
    burst: number;
    diffusion: number;
  };
  evidence: {
    first_mention: number | null;
    takeoff_year: number | null;
    series: Array<{ year: number; count: number; freq_per_million: number }>;
    n_docs: number;
    n_countries: number;
    n_orgs: number | null;
    n_patents: number | null;
  };
  sources: Array<{
    doc_id: string;
    title: string;
    url: string;
    year: number;
    type: string;
  }>;
  stage: "emerging" | "early_growth" | "scaling";
  confidence: "high" | "medium" | "low";
};

export type TrendsResponse = {
  domain: {
    query: string;
    resolved: string;
    n_works: number;
  };
  as_of: number;
  generated_at: string;
  methodology_version: string;
  trends: Trend[];
};

export async function getTrends(
  domainId: string,
  asOf: number,
): Promise<TrendsResponse> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;

  if (!apiUrl) {
    const mock = asOf === 2021 ? mockTrends2021 : mockTrends;
    return {
      ...(mock as TrendsResponse),
      domain: {
        ...(mock as TrendsResponse).domain,
        query: domainId,
      },
    };
  }

  const response = await fetch(`${apiUrl}/api/v1/trends`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain: domainId, as_of: asOf }),
  });

  if (!response.ok) {
    throw new Error(`TrendRadar API returned ${response.status}`);
  }

  return (await response.json()) as TrendsResponse;
}
