import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  TextInput,
  RefreshControl,
  SafeAreaView,
  StatusBar
} from 'react-native';

interface PortfolioSummary {
  equity: number;
  cash: number;
  total_pnl: number;
  total_pnl_pct: number;
  win_rate: number;
  active_positions: any[];
  recent_trades: any[];
}

interface AIDecision {
  signal: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  suggested_allocation_pct: number;
  stop_loss_price: number;
  take_profit_price: number;
  rationale: string;
}

export default function App() {
  const [serverUrl, setServerUrl] = useState('http://10.0.2.2:8080'); // Local emulator host
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [botActive, setBotActive] = useState(false);
  const [price, setPrice] = useState<number>(68450);
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [aiDecision, setAiDecision] = useState<AIDecision | null>(null);
  const [indicators, setIndicators] = useState<any>({ rsi: 50, ema_9: 68400, ema_21: 68300, macd: 0 });

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${serverUrl}/api/status`);
      const data = await res.json();
      setBotActive(data.bot_active);
      setPrice(data.current_price);
      setSymbol(data.symbol);
      setPortfolio(data.portfolio);
      setAiDecision(data.ai_decision);
      setIndicators(data.indicators);
    } catch (err: any) {
      console.log('Error fetching status:', err.message);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [serverUrl]);

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchStatus();
    setRefreshing(false);
  };

  const toggleBot = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${serverUrl}/api/bot/toggle`, { method: 'POST' });
      const data = await res.json();
      setBotActive(data.bot_active);
      Alert.alert('Bot Status', data.message);
    } catch (e: any) {
      Alert.alert('Connection Error', 'Could not reach trading bot backend.');
    } finally {
      setLoading(false);
    }
  };

  const triggerAIAnalysis = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${serverUrl}/api/analyze`, { method: 'POST' });
      const data = await res.json();
      setAiDecision(data.ai_decision);
      Alert.alert('AI Analysis Updated', `Signal: ${data.ai_decision.signal}`);
    } catch (e: any) {
      Alert.alert('Error', 'Failed to run AI model analysis.');
    } finally {
      setLoading(false);
    }
  };

  const sendManualTrade = async (side: 'BUY' | 'SELL') => {
    try {
      const res = await fetch(`${serverUrl}/api/trade/manual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ side, allocation: 0.05 }),
      });
      const data = await res.json();
      Alert.alert('Order Submitted', JSON.stringify(data));
      fetchStatus();
    } catch (e: any) {
      Alert.alert('Error', 'Order execution failed.');
    }
  };

  const getSignalColor = (sig?: string) => {
    if (sig === 'BUY') return '#00E676';
    if (sig === 'SELL') return '#FF5252';
    return '#FFD600';
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor="#0F172A" />
      <ScrollView
        style={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#38BDF8" />}
      >
        {/* Header */}
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>AI TRADING BOT</Text>
            <Text style={styles.subtitle}>Gemini 3.6 Flash Engine</Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: botActive ? '#059669' : '#4B5563' }]}>
            <Text style={styles.statusBadgeText}>{botActive ? '● AUTO RUNNING' : 'PAUSED'}</Text>
          </View>
        </View>

        {/* Server Endpoint Bar */}
        <View style={styles.inputBar}>
          <Text style={styles.inputLabel}>Backend API:</Text>
          <TextInput
            style={styles.input}
            value={serverUrl}
            onChangeText={setServerUrl}
            placeholder="http://your-server:8080"
            placeholderTextColor="#64748B"
            autoCapitalize="none"
          />
        </View>

        {/* Balance Card */}
        <View style={styles.card}>
          <Text style={styles.cardLabel}>TOTAL EQUITY</Text>
          <Text style={styles.equityText}>
            ${portfolio ? portfolio.equity.toLocaleString('en-US', { minimumFractionDigits: 2 }) : '10,000.00'}
          </Text>
          <View style={styles.rowBetween}>
            <Text style={styles.cardSubtext}>
              Available Cash: ${portfolio ? portfolio.cash.toFixed(2) : '10,000.00'}
            </Text>
            <Text
              style={[
                styles.pnlText,
                { color: (portfolio?.total_pnl ?? 0) >= 0 ? '#00E676' : '#FF5252' },
              ]}
            >
              {(portfolio?.total_pnl ?? 0) >= 0 ? '+' : ''}
              ${portfolio?.total_pnl?.toFixed(2) ?? '0.00'} ({portfolio?.total_pnl_pct?.toFixed(2) ?? '0.00'}%)
            </Text>
          </View>
        </View>

        {/* Market & Indicators */}
        <View style={styles.card}>
          <View style={styles.rowBetween}>
            <Text style={styles.symbolText}>{symbol}</Text>
            <Text style={styles.priceText}>${price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</Text>
          </View>
          <View style={styles.indicatorRow}>
            <View style={styles.indicatorBadge}>
              <Text style={styles.indLabel}>RSI (14)</Text>
              <Text style={styles.indVal}>{indicators?.rsi?.toFixed(1) ?? '50.0'}</Text>
            </View>
            <View style={styles.indicatorBadge}>
              <Text style={styles.indLabel}>EMA 9/21</Text>
              <Text style={styles.indVal}>{indicators?.ema_9 > indicators?.ema_21 ? 'BULL' : 'BEAR'}</Text>
            </View>
            <View style={styles.indicatorBadge}>
              <Text style={styles.indLabel}>MACD</Text>
              <Text style={styles.indVal}>{indicators?.macd?.toFixed(2) ?? '0.0'}</Text>
            </View>
          </View>
        </View>

        {/* AI Signal Intelligence Card */}
        <View style={[styles.card, styles.aiCard]}>
          <View style={styles.rowBetween}>
            <Text style={styles.aiCardHeader}>AI PREDICTIVE SIGNAL</Text>
            <TouchableOpacity onPress={triggerAIAnalysis} style={styles.smallButton}>
              <Text style={styles.smallButtonText}>Analyze Now</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.signalBanner}>
            <Text style={[styles.signalText, { color: getSignalColor(aiDecision?.signal) }]}>
              {aiDecision?.signal || 'HOLD'}
            </Text>
            <Text style={styles.confidenceText}>
              Confidence: {((aiDecision?.confidence ?? 0.5) * 100).toFixed(0)}%
            </Text>
          </View>

          <Text style={styles.rationaleText}>
            {aiDecision?.rationale || 'Evaluating price action and technical momentum...'}
          </Text>

          {aiDecision && (
            <View style={styles.levelsRow}>
              <Text style={styles.levelText}>SL: ${aiDecision.stop_loss_price?.toFixed(2)}</Text>
              <Text style={styles.levelText}>TP: ${aiDecision.take_profit_price?.toFixed(2)}</Text>
            </View>
          )}
        </View>

        {/* Bot Controls */}
        <TouchableOpacity
          style={[styles.mainButton, { backgroundColor: botActive ? '#DC2626' : '#16A34A' }]}
          onPress={toggleBot}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#FFF" />
          ) : (
            <Text style={styles.mainButtonText}>{botActive ? 'PAUSE AI AUTO-TRADER' : 'START AI AUTO-TRADER'}</Text>
          )}
        </TouchableOpacity>

        {/* Manual Trade Controls */}
        <View style={styles.actionRow}>
          <TouchableOpacity
            style={[styles.tradeButton, { backgroundColor: '#10B981' }]}
            onPress={() => sendManualTrade('BUY')}
          >
            <Text style={styles.tradeButtonText}>BUY 5%</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tradeButton, { backgroundColor: '#EF4444' }]}
            onPress={() => sendManualTrade('SELL')}
          >
            <Text style={styles.tradeButtonText}>SELL 5%</Text>
          </TouchableOpacity>
        </View>

        {/* Active Positions */}
        <View style={styles.card}>
          <Text style={styles.cardLabel}>ACTIVE POSITIONS</Text>
          {portfolio?.active_positions?.length ? (
            portfolio.active_positions.map((pos, i) => (
              <View key={i} style={styles.positionRow}>
                <View>
                  <Text style={styles.posSymbol}>{pos.symbol}</Text>
                  <Text style={styles.posSub}>Entry: ${pos.entry_price?.toFixed(2)}</Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={[styles.posPnl, { color: pos.unrealized_pnl >= 0 ? '#00E676' : '#FF5252' }]}>
                    {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl?.toFixed(2)} ({pos.unrealized_pnl_pct?.toFixed(2)}%)
                  </Text>
                  <Text style={styles.posSub}>Val: ${pos.current_value?.toFixed(2)}</Text>
                </View>
              </View>
            ))
          ) : (
            <Text style={styles.emptyText}>No open positions. Bot is scanning for opportunities.</Text>
          )}
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#0B0F17' },
  container: { flex: 1, padding: 16 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  title: { fontSize: 20, fontWeight: '900', color: '#F8FAFC', letterSpacing: 0.5 },
  subtitle: { fontSize: 12, color: '#38BDF8', marginTop: 2 },
  statusBadge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12 },
  statusBadgeText: { color: '#FFFFFF', fontSize: 11, fontWeight: 'bold' },
  inputBar: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#1E293B', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6, marginBottom: 12 },
  inputLabel: { color: '#94A3B8', fontSize: 11, marginRight: 6 },
  input: { flex: 1, color: '#F8FAFC', fontSize: 12, padding: 0 },
  card: { backgroundColor: '#161F30', borderRadius: 12, padding: 16, marginBottom: 12, borderWidth: 1, borderColor: '#1E293B' },
  cardLabel: { fontSize: 11, color: '#64748B', fontWeight: 'bold', letterSpacing: 0.5, marginBottom: 6 },
  equityText: { fontSize: 28, fontWeight: 'bold', color: '#FFFFFF', marginBottom: 4 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  cardSubtext: { fontSize: 12, color: '#94A3B8' },
  pnlText: { fontSize: 14, fontWeight: 'bold' },
  symbolText: { fontSize: 18, fontWeight: 'bold', color: '#FFFFFF' },
  priceText: { fontSize: 18, fontWeight: 'bold', color: '#38BDF8' },
  indicatorRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 12 },
  indicatorBadge: { backgroundColor: '#0F172A', paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8, alignItems: 'center', flex: 1, marginHorizontal: 3 },
  indLabel: { color: '#64748B', fontSize: 10, fontWeight: 'bold' },
  indVal: { color: '#F8FAFC', fontSize: 13, fontWeight: 'bold', marginTop: 2 },
  aiCard: { borderColor: '#1E3A8A', backgroundColor: '#0B132B' },
  aiCardHeader: { color: '#60A5FA', fontSize: 11, fontWeight: 'bold', letterSpacing: 0.5 },
  smallButton: { backgroundColor: '#1E293B', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  smallButtonText: { color: '#38BDF8', fontSize: 11, fontWeight: 'bold' },
  signalBanner: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginVertical: 8 },
  signalText: { fontSize: 24, fontWeight: '900' },
  confidenceText: { fontSize: 13, color: '#CBD5E1', fontWeight: '600' },
  rationaleText: { fontSize: 12, color: '#94A3B8', lineHeight: 18, marginTop: 4 },
  levelsRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 10, paddingTop: 8, borderTopWidth: 1, borderTopColor: '#1E293B' },
  levelText: { fontSize: 11, color: '#64748B', fontWeight: '600' },
  mainButton: { height: 48, borderRadius: 10, justifyContent: 'center', alignItems: 'center', marginBottom: 10 },
  mainButtonText: { color: '#FFFFFF', fontSize: 15, fontWeight: 'bold' },
  actionRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 12 },
  tradeButton: { flex: 1, height: 44, borderRadius: 8, justifyContent: 'center', alignItems: 'center', marginHorizontal: 4 },
  tradeButtonText: { color: '#FFFFFF', fontSize: 13, fontWeight: 'bold' },
  positionRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#1E293B' },
  posSymbol: { color: '#FFFFFF', fontWeight: 'bold', fontSize: 14 },
  posSub: { color: '#64748B', fontSize: 11, marginTop: 2 },
  posPnl: { fontWeight: 'bold', fontSize: 13 },
  emptyText: { color: '#64748B', fontSize: 12, fontStyle: 'italic', marginTop: 4 },
});