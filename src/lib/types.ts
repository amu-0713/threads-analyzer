export type Scope = "all" | "real";
export type Source = "real" | "mock";
export type GroupName = "低迷型" | "討論型" | "共鳴型";

export type Job = {
  id: string;
  username: string;
  status: "pending" | "scraping" | "analyzing" | "done" | "failed";
  post_count: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export type Post = {
  id: string;
  job_id: string;
  post_url: string;
  posted_at: string | null;
  text: string | null;
  views: number | null;
  views_rounded: boolean;
  likes: number;
  replies: number;
  reposts: number;
  quotes: number;
  char_count: number;
  hashtag_count: number;
  mention_count: number;
  url_count: number;
  post_type: string | null;
  group: string | null;
  source: Source;
};

export type BriefPost = {
  post_url: string;
  source: Source;
  posted_at: string;
  text: string;
  views: number | null;
  views_rounded?: boolean;
  post_type?: string | null;
  likes: number;
  replies: number;
  reposts: number;
  quotes: number;
  interaction_rate: number | null;
  like_pct?: number;
  reply_pct?: number;
};

export type Profile = {
  n: number;
  avg_views: number | null;
  avg_like_rate: number | null;
  avg_reply_rate: number | null;
  avg_char_count: number | null;
  keywords: { word: string; posts: number }[];
  post_types: { type: string; n: number }[];
  question_share: number | null;
  evening_share: number | null;
  link_share: number | null;
};

export type Metrics = {
  n_posts: number;
  n_real: number;
  n_mock: number;
  avg: Record<"likes" | "replies" | "reposts" | "quotes" | "views" | "char_count", number | null>;
  median: Record<"likes" | "replies" | "reposts" | "quotes", number | null>;
  avg_interaction_rate: number | null;
  avg_like_rate: number | null;
  avg_reply_rate: number | null;
  time_distribution: {
    weekdays: string[];
    slots: string[];
    counts: number[][];
    avg_interaction_rate: (number | null)[][];
  };
  length_vs_interaction: { bins: { label: string; n: number; avg_interaction_rate: number | null }[]; spearman: number | null };
  keywords: { word: string; posts: number }[];
  hashtags: { tag: string; count: number }[];
  post_types: { type: string; n: number; share: number; avg_interaction_rate: number | null }[];
};

export type GroupAnalysis = {
  rules: string;
  median_views: number | null;
  counts: Record<string, number>;
  assignments: Record<string, string>;
  groups: Record<GroupName, { n_members: number; representatives: BriefPost[]; profile_of_representatives: Profile | null }>;
};

export type Insight = { key: string; title: string; verdict: string; text: string };

export type Summary = {
  job_id: string;
  metrics: Partial<Record<Scope, Metrics>>;
  top_posts: Partial<Record<Scope, BriefPost[]>>;
  group_analysis: Partial<Record<Scope, GroupAnalysis>>;
  insights: Partial<Record<Scope, Insight[]>>;
  llm_advice: string | null;
  updated_at: string;
};
