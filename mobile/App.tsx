import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';

type Signal = 'BUY' | 'SELL' | 'HOLD';

interface AIDecision {
  signal: Signal;
  confidence: number;
  suggested_allocation_pct?: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  risk_reward_ratio?: number;
  rationale?: string;
}

interface Position {
  symbol: string;
  direction?: string;
  entry_price?: number;
  current_price?: number;
  current_value?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  stop_loss?: number;
  take_profit?: number;
}

interface PortfolioSummary {
  equity: number;
  cash: number;
  total_pnl: number;
  total_pnl_pct: number;
  win_rate: number;
  expectancy_per_trade?: number;
  profit_factor?: number | null;
  current_drawdown_pct?: number;
  active_positions: Position[];
  recent_trades: any[];
  peak_equity?: number;
  daily_realized_pnl?: number;
  max_risk_per_trade_pct?: number;
  max_daily_loss_pct?: number;
  max_drawdown_pct?: number;
  max_open_positions?: number;
  risk_status?: {
    equity?: number;
    peak_equity?: number;
    daily_realized_pnl?: number;
    daily_loss_limit?: number;
    drawdown_limit?: number;
    daily_loss_exceeded?: boolean;
    drawdown_exceeded?: boolean;
    consecutive_loss_lockout?: boolean;
    loss_cooldown_active?: boolean;
    daily_entries?: number;
    max_daily_entries?: number;
    daily_entry_limit_exceeded?: boolean;
  };
}

interface MarketPayload {
  symbol: string;
  price: number | null;
  indicators?: {
    rsi?: number;
    ema_9?: number;
    ema_21?: number;
    macd?: number;
    atr?: number;
  };
  ai_decision?: AIDecision;
  last_update?: number | null;
  error?: string | null;
}

interface StatusResponse {
  status: string;
  bot_active: boolean;
  trading_mode?: string;
  market_data_mode?: string;
  live_execution_enabled?: boolean;
  broker?: string;
  selected_symbol: string;
  symbol: string;
  current_price: number;
  portfolio: PortfolioSummary;
  ai_decision: AIDecision;
  indicators: {
    rsi?: number;
    ema_9?: number;
    ema_21?: number;
    macd?: number;
  };
  markets?: Record<string, MarketPayload>;
  timestamp?: number;
}

interface SMCReport {
  status: string;
  tradable: boolean;
  reason: string;
  data_source: string;
  simulated_data_warning?: string | null;
  timeframes: Record<
    string,
    {
      status: string;
      candle_count?: number;
      evidence?: Array<{
        type: string;
        direction?: string;
        classification?: string;
        time?: string;
        validity?: string;
      }>;
    }
  >;
}

interface PairSnapshot {
  symbol: string;
  price: number | null;
  rsi: number | null;
  ema9: number | null;
  ema21: number | null;
  macd: number | null;
  signal: Signal;
  confidence: number;
  rationale: string;
  stopLoss: number | null;
  takeProfit: number | null;
  loaded: boolean;
}

const PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'GBP/JPY'];

const emptyPair = (symbol: string): PairSnapshot => ({
  symbol,
  price: null,
  rsi: null,
  ema9: null,
  ema21: null,
  macd: null,
  signal: 'HOLD',
  confidence: 0,
  rationale: 'Waiting for the Forex backend feed.',
  stopLoss: null,
  takeProfit: null,
  loaded: false,
});

const formatPrice = (symbol: string, value: number | null | undefined) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return symbol.includes('JPY') ? value.toFixed(3) : value.toFixed(5);
};

const formatMoney = (value: number | undefined) =>
  `$${(value ?? 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const signalColor = (signal: Signal) => {
  if (signal === 'BUY') return '#22C55E';
  if (signal === 'SELL') return '#EF4444';
  return '#FACC15';
};

export default function App() {
  const [serverUrl, setServerUrl] = useState(
    process.env.EXPO_PUBLIC_API_URL?.replace(/\/+$/, '') ||
      (Platform.OS === 'android'
        ? 'http://10.0.2.2:8080'
        : 'http://localhost:8080'),
  );
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedPair, setSelectedPair] = useState('EUR/USD');
  const [pairs, setPairs] = useState<Record<string, PairSnapshot>>(
    Object.fromEntries(PAIRS.map((pair) => [pair, emptyPair(pair)])),
  );
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [backendOnline, setBackendOnline] = useState(false);
  const [marketDataMode, setMarketDataMode] = useState('unknown');
  const [brokerStatus, setBrokerStatus] = useState('not checked');
  const [brokerCheckLoading, setBrokerCheckLoading] = useState(false);
  const [authToken, setAuthToken] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authenticatedEmail, setAuthenticatedEmail] = useState('');
  const [smcReport, setSmcReport] = useState<SMCReport | null>(null);
  const [smcLoading, setSmcLoading] = useState(false);
  const [tradingMode, setTradingMode] = useState<'analysis' | 'assisted'>('analysis');
  const [stopLossInput, setStopLossInput] = useState('');
  const [takeProfitInput, setTakeProfitInput] = useState('');
  const [orderLoading, setOrderLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      if (!authToken) {
        const health = await fetch(`${serverUrl}/api/health`);
        setBackendOnline(health.ok);
        if (health.ok) {
          const data = await health.json();
          setMarketDataMode(data.market_data_mode ?? 'unknown');
        }
        return;
      }
      const response = await fetch(`${serverUrl}/api/status`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data: StatusResponse = await response.json();

      const marketPayloads = data.markets ?? {};

      const updatedPairs: Record<string, PairSnapshot> = {};

      for (const pair of PAIRS) {
        const market = marketPayloads[pair];

        if (market) {
          updatedPairs[pair] = {
            symbol: pair,
            price: market.price ?? null,
            rsi: market.indicators?.rsi ?? null,
            ema9: market.indicators?.ema_9 ?? null,
            ema21: market.indicators?.ema_21 ?? null,
            macd: market.indicators?.macd ?? null,
            signal: market.ai_decision?.signal ?? 'HOLD',
            confidence: market.ai_decision?.confidence ?? 0,
            rationale:
              market.ai_decision?.rationale ??
              'Technical evidence is being evaluated.',
            stopLoss: market.ai_decision?.stop_loss_price ?? null,
            takeProfit: market.ai_decision?.take_profit_price ?? null,
            loaded: market.price !== null && market.price !== undefined,
          };
        }
      }

      // Backward-compatible fallback for the selected pair.
      if (!updatedPairs[data.symbol]) {
        updatedPairs[data.symbol] = {
          symbol: data.symbol,
          price: data.current_price,
          rsi: data.indicators?.rsi ?? null,
          ema9: data.indicators?.ema_9 ?? null,
          ema21: data.indicators?.ema_21 ?? null,
          macd: data.indicators?.macd ?? null,
          signal: data.ai_decision?.signal ?? 'HOLD',
          confidence: data.ai_decision?.confidence ?? 0,
          rationale:
            data.ai_decision?.rationale ??
            'Technical evidence is being evaluated.',
          stopLoss: data.ai_decision?.stop_loss_price ?? null,
          takeProfit: data.ai_decision?.take_profit_price ?? null,
          loaded: true,
        };
      }

      setPairs((previous) => ({
        ...previous,
        ...updatedPairs,
      }));
      setTradingMode(data.trading_mode === 'assisted' ? 'assisted' : 'analysis');
      setMarketDataMode(data.market_data_mode ?? 'unknown');
      setPortfolio(data.portfolio ?? null);
      setBackendOnline(true);
    } catch (error) {
      console.log('Status error:', error);
      setBackendOnline(false);
    }
  }, [serverUrl, authToken]);

  const fetchTrades = useCallback(async () => {
    if (!authToken) return;
    try {
      const response = await fetch(`${serverUrl}/api/trades`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) return;
      const data = await response.json();
      setTrades(Array.isArray(data.trades) ? data.trades : []);
    } catch (error) {
      console.log('Trades error:', error);
    }
  }, [serverUrl, authToken]);

  useEffect(() => {
    fetchStatus();
    fetchTrades();

    const interval = setInterval(() => {
      fetchStatus();
      fetchTrades();
    }, 5000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchTrades]);

  const selected = pairs[selectedPair] ?? emptyPair(selectedPair);

  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([fetchStatus(), fetchTrades()]);
    setRefreshing(false);
  };

  const authenticate = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${serverUrl}/api/auth/${authMode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
      setAuthToken(data.token);
      setAuthenticatedEmail(data.email);
      setPassword('');
    } catch (error) {
      Alert.alert(
        'Account error',
        error instanceof Error ? error.message : 'Could not reach the local backend.',
      );
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await fetch(`${serverUrl}/api/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}` },
      });
    } finally {
      setAuthToken('');
      setAuthenticatedEmail('');
      setPortfolio(null);
      setTrades([]);
      setSmcReport(null);
      setBrokerStatus('not checked');
      setMarketDataMode('unknown');
    }
  };

  const checkMt5Connection = async () => {
    try {
      setBrokerCheckLoading(true);
      const response = await fetch(`${serverUrl}/api/broker/status`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      const data = await response.json();
      if (!response.ok || !data.connected) {
        throw new Error(data.reason ?? `HTTP ${response.status}`);
      }
      const message = `MT5 linked read-only${data.server ? ` • ${data.server}` : ''}`;
      setBrokerStatus(message);
      Alert.alert(
        'MT5 connection confirmed',
        `${message}\nLive order submission remains disabled.`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Connection check failed.';
      setBrokerStatus('connection check failed');
      Alert.alert('MT5 connection unavailable', message);
    } finally {
      setBrokerCheckLoading(false);
    }
  };

  const setMode = async (mode: 'analysis' | 'assisted') => {
    try {
      const response = await fetch(`${serverUrl}/api/mode`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ mode }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? data.reason ?? 'Mode update failed.');
      setTradingMode(mode);
    } catch (error) {
      Alert.alert('Mode update failed', error instanceof Error ? error.message : 'Request failed.');
    }
  };

  const analyzeSMC = async () => {
    try {
      setSmcLoading(true);
      const response = await fetch(`${serverUrl}/api/smc/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ symbol: selectedPair, config: {} }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? 'SMC analysis failed.');
      setSmcReport(data as SMCReport);
    } catch (error) {
      Alert.alert('SMC analysis unavailable', error instanceof Error ? error.message : 'Request failed.');
    } finally {
      setSmcLoading(false);
    }
  };

  const requestPaperTrade = (side: 'BUY' | 'SELL') => {
    if (!stopLossInput || !takeProfitInput) {
      Alert.alert('Required levels', 'Enter a stop loss and take profit before requesting a paper trade.');
      return;
    }
    Alert.alert(
      `Confirm paper ${side}`,
      `${selectedPair}\nStop loss: ${stopLossInput}\nTake profit: ${takeProfitInput}\nMaximum nominal risk: 0.25% of current equity.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm paper order',
          onPress: () => { void submitPaperTrade(side); },
        },
      ],
    );
  };

  const submitPaperTrade = async (side: 'BUY' | 'SELL') => {
    try {
      setOrderLoading(true);
      const response = await fetch(`${serverUrl}/api/trade/manual`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          symbol: selectedPair,
          side,
          stop_loss_price: Number(stopLossInput),
          take_profit_price: Number(takeProfitInput),
          confirm: true,
          idempotency_key: `${Date.now()}-${side}`,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.status !== 'executed') {
        throw new Error(data.reason ?? data.error ?? 'Paper order rejected.');
      }
      Alert.alert('Paper order confirmed', `Simulated broker order ${data.broker_order_id} was confirmed.`);
      await Promise.all([fetchStatus(), fetchTrades()]);
    } catch (error) {
      Alert.alert(
        'Paper order status uncertain',
        `${error instanceof Error ? error.message : 'Request failed.'} Check trade history before retrying.`,
      );
    } finally {
      setOrderLoading(false);
    }
  };

  const resetLossLockout = async () => {
    try {
      const response = await fetch(`${serverUrl}/api/risk/reset`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ confirm: true }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.reason ?? data.error ?? 'Reset rejected.');
      Alert.alert('Risk lockout reset', data.message ?? 'Daily and drawdown limits remain active.');
      await fetchStatus();
    } catch (error) {
      Alert.alert('Reset rejected', error instanceof Error ? error.message : 'Request failed.');
    }
  };

  const analyzeSelected = async () => {
    try {
      setLoading(true);
      const response = await fetch(
        `${serverUrl}/api/analyze?symbol=${encodeURIComponent(selectedPair)}`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${authToken}` },
        },
      );
      const data = await response.json();

      if (data.ai_decision) {
        setPairs((previous) => ({
          ...previous,
          [selectedPair]: {
            ...previous[selectedPair],
            signal: data.ai_decision.signal ?? 'HOLD',
            confidence: data.ai_decision.confidence ?? 0,
            rationale: data.ai_decision.rationale ?? '',
            stopLoss: data.ai_decision.stop_loss_price ?? null,
            takeProfit: data.ai_decision.take_profit_price ?? null,
            loaded: true,
          },
        }));
      }
      await fetchStatus();
    } catch {
      Alert.alert('Analysis error', 'The AI analysis request failed.');
    } finally {
      setLoading(false);
    }
  };

  const openPositions = portfolio?.active_positions ?? [];
  const riskStatus = portfolio?.risk_status;

  const riskLabel = useMemo(() => {
    if (!riskStatus) return 'RISK CHECK PENDING';
    if (
      riskStatus.daily_loss_exceeded ||
      riskStatus.drawdown_exceeded ||
      riskStatus.consecutive_loss_lockout ||
      riskStatus.loss_cooldown_active ||
      riskStatus.daily_entry_limit_exceeded
    ) {
      return 'TRADING BLOCKED';
    }
    return 'RISK LIMITS OK';
  }, [riskStatus]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor="#080D16" />

      <ScrollView
        style={styles.container}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#38BDF8"
          />
        }
      >
        {authToken ? (
          <>
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>AI FOREX TRADING BOT</Text>
            <Text style={styles.subtitle}>
              {authenticatedEmail} • Local paper mode • Live trading disabled
            </Text>
          </View>
          <TouchableOpacity onPress={logout} style={styles.smallButton}>
            <Text style={styles.smallButtonText}>SIGN OUT</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.connectionRow}>
          <View
            style={[
              styles.dot,
              { backgroundColor: backendOnline ? '#22C55E' : '#EF4444' },
            ]}
          />
          <Text style={styles.connectionText}>
            BACKEND {backendOnline ? 'ONLINE' : 'OFFLINE'}
          </Text>
          <Text style={styles.modeText}>MODE: {tradingMode.toUpperCase()}</Text>
        </View>
        <View style={styles.connectionRow}>
          <Text style={styles.modeText}>
            MARKET DATA: {marketDataMode.toUpperCase()}
          </Text>
          <TouchableOpacity
            onPress={checkMt5Connection}
            style={styles.smallButton}
            disabled={brokerCheckLoading}
          >
            {brokerCheckLoading ? (
              <ActivityIndicator size="small" color="#38BDF8" />
            ) : (
              <Text style={styles.smallButtonText}>CHECK MT5 (READ ONLY)</Text>
            )}
          </TouchableOpacity>
        </View>
        <Text style={styles.positionSub}>MT5: {brokerStatus}</Text>

        <View style={styles.inputBar}>
          <Text style={styles.inputLabel}>Backend:</Text>
          <TextInput
            style={styles.input}
            value={serverUrl}
            onChangeText={setServerUrl}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="http://localhost:8080"
            placeholderTextColor="#64748B"
          />
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionLabel}>MARKET WATCH</Text>

          <View style={styles.pairGrid}>
            {PAIRS.map((pair) => {
              const item = pairs[pair] ?? emptyPair(pair);
              const active = selectedPair === pair;

              return (
                <TouchableOpacity
                  key={pair}
                  style={[styles.pairCard, active && styles.pairCardActive]}
                  onPress={() => setSelectedPair(pair)}
                >
                  <View style={styles.pairTop}>
                    <Text style={styles.pairName}>{pair}</Text>
                    <Text
                      style={[
                        styles.miniSignal,
                        { color: signalColor(item.signal) },
                      ]}
                    >
                      {item.signal}
                    </Text>
                  </View>

                  <Text style={styles.pairPrice}>
                    {item.loaded ? formatPrice(pair, item.price) : '—'}
                  </Text>

                  <View style={styles.miniRow}>
                    <Text style={styles.miniLabel}>RSI</Text>
                    <Text style={styles.miniValue}>
                      {item.rsi === null ? '—' : item.rsi.toFixed(1)}
                    </Text>
                    <Text style={styles.miniLabel}>EMA</Text>
                    <Text style={styles.miniValue}>
                      {item.ema9 !== null && item.ema21 !== null
                        ? item.ema9 > item.ema21
                          ? 'BULL'
                          : 'BEAR'
                        : '—'}
                    </Text>
                  </View>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={styles.feedNote}>
            Feed mode: {marketDataMode}. Simulated candles are not live prices.
            AI indicator context is not SMC and cannot trigger orders.
          </Text>
        </View>

        <View style={styles.card}>
          <View style={styles.rowBetween}>
            <View>
              <Text style={styles.sectionLabel}>SELECTED MARKET</Text>
              <Text style={styles.selectedSymbol}>{selectedPair}</Text>
            </View>
            <Text style={styles.selectedPrice}>
              {formatPrice(selectedPair, selected.price)}
            </Text>
          </View>

          <View style={styles.indicatorGrid}>
            <Indicator label="RSI (14)" value={selected.rsi === null ? '—' : selected.rsi.toFixed(1)} />
            <Indicator
              label="EMA 9 / 21"
              value={
                selected.ema9 !== null && selected.ema21 !== null
                  ? selected.ema9 > selected.ema21
                    ? 'BULL'
                    : 'BEAR'
                  : '—'
              }
            />
            <Indicator label="MACD" value={selected.macd === null ? '—' : selected.macd.toFixed(6)} />
          </View>
        </View>

        <View style={styles.aiCard}>
          <View style={styles.rowBetween}>
            <View>
              <Text style={styles.aiHeader}>LEGACY INDICATOR CONTEXT</Text>
              <Text style={styles.aiPair}>{selectedPair}</Text>
            </View>

            <TouchableOpacity
              onPress={analyzeSelected}
              style={styles.smallButton}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator size="small" color="#38BDF8" />
              ) : (
                <Text style={styles.smallButtonText}>ANALYZE</Text>
              )}
            </TouchableOpacity>
          </View>

          <View style={styles.signalRow}>
            <Text
              style={[
                styles.signalText,
                { color: signalColor(selected.signal) },
              ]}
            >
              {selected.signal}
            </Text>
            <Text style={styles.confidence}>
              Informational {selected.signal} • score is not probability
            </Text>
          </View>

          <View style={styles.card}>
            <View style={styles.rowBetween}>
              <View>
                <Text style={styles.sectionLabel}>SMC EVIDENCE (ANALYSIS ONLY)</Text>
                <Text style={styles.positionSub}>
                  No executable setup until your thresholds are approved.
                </Text>
              </View>
              <TouchableOpacity onPress={analyzeSMC} style={styles.smallButton} disabled={smcLoading}>
                {smcLoading ? (
                  <ActivityIndicator size="small" color="#38BDF8" />
                ) : (
                  <Text style={styles.smallButtonText}>SCAN SMC</Text>
                )}
              </TouchableOpacity>
            </View>
            {smcReport ? (
              <>
                <Text style={styles.riskBannerText}>
                  {smcReport.simulated_data_warning ?? smcReport.reason}
                </Text>
                {Object.entries(smcReport.timeframes).map(([timeframe, detail]) => (
                  <Text key={timeframe} style={styles.positionSub}>
                    {timeframe}: {detail.status} • {detail.evidence?.length ?? 0} evidence item(s)
                  </Text>
                ))}
              </>
            ) : (
              <Text style={styles.emptyText}>
                Configure SMC swing, liquidity, displacement, FVG, and Order Block
                thresholds in an approved strategy configuration before using
                these findings.
              </Text>
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionLabel}>TRADING MODE</Text>
            <View style={styles.pairGrid}>
              {(['analysis', 'assisted'] as const).map((mode) => (
                <TouchableOpacity
                  key={mode}
                  style={[styles.pairCard, tradingMode === mode && styles.pairCardActive]}
                  onPress={() => setMode(mode)}
                >
                  <Text style={styles.pairName}>{mode.toUpperCase()}</Text>
                  <Text style={styles.positionSub}>
                    {mode === 'analysis' ? 'No orders' : 'Manual paper approval only'}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.emptyText}>
              Automated trading is disabled until SMC thresholds, validation,
              broker integration tests, and explicit authorization are complete.
            </Text>
          </View>

          {tradingMode === 'assisted' && (
            <View style={styles.card}>
              <Text style={styles.sectionLabel}>MANUAL PAPER TRADE</Text>
              <Text style={styles.positionSub}>
                Order approval is explicit. Risk engine can still reject it.
              </Text>
              <TextInput
                style={styles.input}
                value={stopLossInput}
                onChangeText={setStopLossInput}
                keyboardType="decimal-pad"
                placeholder="Stop loss price"
                placeholderTextColor="#64748B"
              />
              <TextInput
                style={styles.input}
                value={takeProfitInput}
                onChangeText={setTakeProfitInput}
                keyboardType="decimal-pad"
                placeholder="Take profit price"
                placeholderTextColor="#64748B"
              />
              <View style={styles.signalRow}>
                {(['BUY', 'SELL'] as const).map((side) => (
                  <TouchableOpacity
                    key={side}
                    style={[styles.smallButton, { borderColor: signalColor(side) }]}
                    onPress={() => requestPaperTrade(side)}
                    disabled={orderLoading}
                  >
                    <Text style={[styles.smallButtonText, { color: signalColor(side) }]}>
                      PAPER {side}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          )}

          <Text style={styles.rationale}>{selected.rationale}</Text>

          <View style={styles.levels}>
            <Level label="STOP LOSS" value={formatPrice(selectedPair, selected.stopLoss)} />
            <Level label="TAKE PROFIT" value={formatPrice(selectedPair, selected.takeProfit)} />
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionLabel}>ACCOUNT & RISK</Text>

          <View style={styles.accountGrid}>
            <Metric label="EQUITY" value={formatMoney(portfolio?.equity)} />
            <Metric label="CASH" value={formatMoney(portfolio?.cash)} />
            <Metric
              label="P&L"
              value={`${(portfolio?.total_pnl ?? 0) >= 0 ? '+' : ''}${formatMoney(portfolio?.total_pnl)} (${(portfolio?.total_pnl_pct ?? 0).toFixed(2)}%)`}
            />
            <Metric
              label="RISK / TRADE"
              value={`${((portfolio?.max_risk_per_trade_pct ?? 0) * 100).toFixed(2)}%`}
            />
            <Metric label="WIN RATE" value={`${(portfolio?.win_rate ?? 0).toFixed(1)}%`} />
            <Metric
              label="PROFIT FACTOR"
              value={portfolio?.profit_factor == null ? '—' : portfolio.profit_factor.toFixed(2)}
            />
            <Metric
              label="EXPECTANCY / TRADE"
              value={formatMoney(portfolio?.expectancy_per_trade)}
            />
            <Metric
              label="CURRENT DRAWDOWN"
              value={`${(portfolio?.current_drawdown_pct ?? 0).toFixed(2)}%`}
            />
          </View>

          <View style={styles.riskBanner}>
            <Text style={styles.riskBannerTitle}>{riskLabel}</Text>
            <Text style={styles.riskBannerText}>
              {riskStatus?.consecutive_loss_lockout
                ? 'Two consecutive losses. Deliberate risk reset is required.'
                : riskStatus?.daily_entry_limit_exceeded
                  ? `Daily entry limit reached: ${riskStatus.daily_entries}/${riskStatus.max_daily_entries}. Resumes at the next UTC risk day.`
                  : riskStatus?.loss_cooldown_active
                    ? 'Loss cooldown active. New entries are temporarily blocked.'
                : `Daily loss limit: ${formatMoney(riskStatus?.daily_loss_limit)} • Drawdown limit: ${formatMoney(riskStatus?.drawdown_limit)}`}
            </Text>
            {riskStatus?.consecutive_loss_lockout && (
              <TouchableOpacity
                style={styles.smallButton}
                onPress={() => {
                  Alert.alert(
                    'Deliberate risk reset',
                    'This clears only the two-loss suspension. Daily loss and drawdown limits will still block trading.',
                    [
                      { text: 'Cancel', style: 'cancel' },
                      {
                        text: 'Reset loss streak',
                        onPress: () => { void resetLossLockout(); },
                      },
                    ],
                  );
                }}
              >
                <Text style={styles.smallButtonText}>DELIBERATE RESET</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        <View style={styles.card}>
          <View style={styles.rowBetween}>
            <Text style={styles.sectionLabel}>ACTIVE POSITIONS</Text>
            <Text style={styles.countText}>{openPositions.length}</Text>
          </View>

          {openPositions.length === 0 ? (
            <Text style={styles.emptyText}>
              No open paper positions. The bot is scanning for opportunities.
            </Text>
          ) : (
            openPositions.map((position, index) => (
              <View key={`${position.symbol}-${index}`} style={styles.positionRow}>
                <View>
                  <Text style={styles.positionSymbol}>{position.symbol}</Text>
                  <Text style={styles.positionSub}>
                    {position.direction ?? 'POSITION'} • Entry {formatPrice(position.symbol, position.entry_price)}
                  </Text>
                </View>

                <View style={styles.positionRight}>
                  <Text
                    style={[
                      styles.positionPnl,
                      {
                        color:
                          (position.unrealized_pnl ?? 0) >= 0
                            ? '#22C55E'
                            : '#EF4444',
                      },
                    ]}
                  >
                    {(position.unrealized_pnl ?? 0) >= 0 ? '+' : ''}
                    {formatMoney(position.unrealized_pnl)}
                  </Text>
                  <Text style={styles.positionSub}>
                    {formatPrice(position.symbol, position.current_price)}
                  </Text>
                </View>
              </View>
            ))
          )}
        </View>

        <View style={styles.card}>
          <View style={styles.rowBetween}>
            <Text style={styles.sectionLabel}>RECENT PAPER TRADES</Text>
            <Text style={styles.countText}>{trades.length}</Text>
          </View>

          {trades.length === 0 ? (
            <Text style={styles.emptyText}>No paper trades yet.</Text>
          ) : (
            trades.slice(-5).reverse().map((trade, index) => (
              <View key={`${trade.id ?? 'trade'}-${index}`} style={styles.tradeRow}>
                <View>
                  <Text style={styles.positionSymbol}>
                    {trade.symbol ?? '—'} • {trade.type ?? trade.direction ?? 'TRADE'}
                  </Text>
                  <Text style={styles.positionSub}>{trade.time ?? ''}</Text>
                </View>
                <Text style={styles.positionSub}>
                  {formatMoney(trade.usd_value)}
                </Text>
              </View>
            ))
          )}
        </View>

        <View style={styles.warningCard}>
          <Text style={styles.warningTitle}>AUTOMATED AND LIVE TRADING DISABLED</Text>
          <Text style={styles.warningText}>
            SMC evidence is informational only. Live order submission is not
            implemented. Simulated account values and generated prices are not
            evidence of trading performance.
          </Text>
        </View>

        <View style={{ height: 50 }} />
          </>
        ) : (
          <View style={styles.card}>
            <Text style={styles.title}>LOCAL PAPER ACCOUNT</Text>
            <Text style={styles.subtitle}>
              Create an account or sign in. Accounts and paper histories are
              isolated on this computer.
            </Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              placeholder="Email"
              placeholderTextColor="#64748B"
            />
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
              placeholder="Password (at least 12 characters)"
              placeholderTextColor="#64748B"
            />
            <TouchableOpacity
              style={styles.mainButton}
              onPress={authenticate}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color="#FFFFFF" />
              ) : (
                <Text style={styles.mainButtonText}>
                  {authMode === 'login' ? 'SIGN IN' : 'CREATE ACCOUNT'}
                </Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setAuthMode(authMode === 'login' ? 'register' : 'login')}
              style={styles.smallButton}
            >
              <Text style={styles.smallButtonText}>
                {authMode === 'login' ? 'NEW HERE? CREATE ACCOUNT' : 'ALREADY REGISTERED? SIGN IN'}
              </Text>
            </TouchableOpacity>
            <Text style={styles.warningText}>
              Local-only development account. Do not reuse a sensitive password.
              Sessions expire after 12 hours and are held in memory by the app.
            </Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Indicator({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.indicator}>
      <Text style={styles.indicatorLabel}>{label}</Text>
      <Text style={styles.indicatorValue}>{value}</Text>
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

function Level({ label, value }: { label: string; value: string }) {
  return (
    <View>
      <Text style={styles.levelLabel}>{label}</Text>
      <Text style={styles.levelValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#080D16' },
  container: { flex: 1, padding: 16 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  title: {
    fontSize: 20,
    fontWeight: '900',
    color: '#F8FAFC',
    letterSpacing: 0.4,
  },
  subtitle: { fontSize: 11, color: '#38BDF8', marginTop: 3 },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 14,
  },
  statusBadgeText: { color: '#FFF', fontSize: 10, fontWeight: '900' },
  connectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  dot: { width: 7, height: 7, borderRadius: 4, marginRight: 6 },
  connectionText: {
    color: '#94A3B8',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  modeText: {
    marginLeft: 'auto',
    color: '#F59E0B',
    fontSize: 10,
    fontWeight: '900',
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#172033',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginBottom: 12,
  },
  inputLabel: { color: '#64748B', fontSize: 10, marginRight: 7 },
  input: { flex: 1, color: '#F8FAFC', fontSize: 12, padding: 0 },
  card: {
    backgroundColor: '#141D2E',
    borderRadius: 12,
    padding: 15,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#22304A',
  },
  sectionLabel: {
    color: '#64748B',
    fontSize: 10,
    fontWeight: '900',
    letterSpacing: 0.8,
    marginBottom: 8,
  },
  pairGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginHorizontal: -4,
  },
  pairCard: {
    width: '50%',
    padding: 11,
    backgroundColor: '#0D1525',
    borderRadius: 9,
    borderWidth: 1,
    borderColor: '#1E293B',
    marginBottom: 8,
    paddingHorizontal: 10,
  },
  pairCardActive: { borderColor: '#38BDF8', backgroundColor: '#0E1B30' },
  pairTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  pairName: { color: '#F8FAFC', fontSize: 12, fontWeight: '900' },
  miniSignal: { fontSize: 9, fontWeight: '900' },
  pairPrice: {
    color: '#38BDF8',
    fontSize: 18,
    fontWeight: '900',
    marginVertical: 5,
  },
  miniRow: { flexDirection: 'row', alignItems: 'center' },
  miniLabel: { color: '#64748B', fontSize: 8, marginRight: 4 },
  miniValue: { color: '#CBD5E1', fontSize: 9, fontWeight: '800', marginRight: 8 },
  feedNote: { color: '#64748B', fontSize: 10, lineHeight: 15, marginTop: 4 },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  selectedSymbol: { color: '#FFFFFF', fontSize: 22, fontWeight: '900' },
  selectedPrice: { color: '#38BDF8', fontSize: 22, fontWeight: '900' },
  indicatorGrid: {
    flexDirection: 'row',
    marginTop: 14,
    marginHorizontal: -3,
  },
  indicator: {
    flex: 1,
    backgroundColor: '#0D1525',
    borderRadius: 8,
    paddingVertical: 9,
    marginHorizontal: 3,
    alignItems: 'center',
  },
  indicatorLabel: { color: '#64748B', fontSize: 8, fontWeight: '800' },
  indicatorValue: { color: '#F8FAFC', fontSize: 12, fontWeight: '900', marginTop: 3 },
  aiCard: {
    backgroundColor: '#09142B',
    borderRadius: 12,
    padding: 15,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#1D4ED8',
  },
  aiHeader: { color: '#60A5FA', fontSize: 10, fontWeight: '900', letterSpacing: 0.7 },
  aiPair: { color: '#F8FAFC', fontSize: 16, fontWeight: '900', marginTop: 3 },
  smallButton: {
    backgroundColor: '#172033',
    borderRadius: 7,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  smallButtonText: { color: '#38BDF8', fontSize: 9, fontWeight: '900' },
  signalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginVertical: 10,
  },
  signalText: { fontSize: 28, fontWeight: '900' },
  confidence: { color: '#CBD5E1', fontSize: 12, fontWeight: '800' },
  rationale: { color: '#94A3B8', fontSize: 11, lineHeight: 17 },
  levels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
    marginTop: 12,
    paddingTop: 10,
  },
  levelLabel: { color: '#64748B', fontSize: 8, fontWeight: '800' },
  levelValue: { color: '#CBD5E1', fontSize: 12, fontWeight: '900', marginTop: 3 },
  accountGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  metric: {
    width: '50%',
    paddingVertical: 8,
    paddingRight: 8,
  },
  metricLabel: { color: '#64748B', fontSize: 8, fontWeight: '800' },
  metricValue: { color: '#F8FAFC', fontSize: 15, fontWeight: '900', marginTop: 3 },
  riskBanner: {
    marginTop: 8,
    backgroundColor: '#0D1525',
    borderRadius: 8,
    padding: 10,
  },
  riskBannerTitle: { color: '#22C55E', fontSize: 10, fontWeight: '900' },
  riskBannerText: { color: '#64748B', fontSize: 9, marginTop: 3 },
  countText: { color: '#38BDF8', fontSize: 12, fontWeight: '900' },
  emptyText: { color: '#64748B', fontSize: 11, lineHeight: 17 },
  positionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  positionSymbol: { color: '#F8FAFC', fontSize: 12, fontWeight: '900' },
  positionSub: { color: '#64748B', fontSize: 9, marginTop: 3 },
  positionRight: { alignItems: 'flex-end' },
  positionPnl: { fontSize: 12, fontWeight: '900' },
  tradeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  mainButton: {
    height: 48,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
  },
  mainButtonText: { color: '#FFF', fontSize: 13, fontWeight: '900' },
  warningCard: {
    borderRadius: 10,
    padding: 12,
    backgroundColor: '#2A170B',
    borderWidth: 1,
    borderColor: '#7C2D12',
    marginBottom: 12,
  },
  warningTitle: { color: '#FB923C', fontSize: 10, fontWeight: '900' },
  warningText: { color: '#A8A29E', fontSize: 10, lineHeight: 15, marginTop: 5 },
});
