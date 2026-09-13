import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.tsx";
import Agents from "./pages/Agents.tsx";
import Alerts from "./pages/Alerts.tsx";
import Commentary from "./pages/Commentary.tsx";
import Dashboard from "./pages/Dashboard.tsx";
import Health from "./pages/Health.tsx";
import Hedging from "./pages/Hedging.tsx";
import Market from "./pages/Market.tsx";
import Options from "./pages/Options.tsx";
import SettingsPage from "./pages/Settings.tsx";
import Signals from "./pages/Signals.tsx";
import Stocks from "./pages/Stocks.tsx";
import Strategies from "./pages/Strategies.tsx";
import Watchlist from "./pages/Watchlist.tsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="market" element={<Market />} />
        <Route path="stocks" element={<Stocks />} />
        <Route path="options" element={<Options />} />
        <Route path="strategies" element={<Strategies />} />
        <Route path="hedging" element={<Hedging />} />
        <Route path="commentary" element={<Commentary />} />
        <Route path="agents" element={<Agents />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="signals" element={<Signals />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="health" element={<Health />} />
        <Route path="*" element={<Dashboard />} />
      </Route>
    </Routes>
  );
}
