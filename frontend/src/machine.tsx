import React, { createContext, useContext, useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type Machine = "cnc" | "laser";
const KEY = "machine_mode";

type Ctx = { machine: Machine; setMachine: (m: Machine) => void; ready: boolean };
const MachineContext = createContext<Ctx>({ machine: "cnc", setMachine: () => {}, ready: false });

export function MachineProvider({ children }: { children: React.ReactNode }) {
  const [machine, setMachineState] = useState<Machine>("cnc");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(KEY).then((v) => {
      if (v === "cnc" || v === "laser") setMachineState(v);
      setReady(true);
    });
  }, []);

  const setMachine = (m: Machine) => {
    setMachineState(m);
    AsyncStorage.setItem(KEY, m).catch(() => {});
  };

  return (
    <MachineContext.Provider value={{ machine, setMachine, ready }}>
      {children}
    </MachineContext.Provider>
  );
}

export const useMachine = () => useContext(MachineContext);
