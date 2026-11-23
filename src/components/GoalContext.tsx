"use client";

import { createContext, useContext, useState } from "react";
import { GOALS, type Goal } from "@/lib/advice";

const Ctx = createContext<{ goal: Goal; setGoal: (g: Goal) => void }>({ goal: GOALS[0], setGoal: () => {} });

/** The goal picked in the AI advice section; the rewrite example of the writing guide follows it. */
export function GoalProvider({ children }: { children: React.ReactNode }) {
  const [goal, setGoal] = useState<Goal>(GOALS[0]);
  return <Ctx.Provider value={{ goal, setGoal }}>{children}</Ctx.Provider>;
}

export const useGoal = () => useContext(Ctx);
