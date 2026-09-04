import React from 'react';
import { createRoot } from 'react-dom/client';
import '../../src/index.css';
import { PosProvider } from './contexts';
import { ManagementLayout } from '../../src/layouts/ManagementLayout';
import { PosLayout } from '../../src/layouts/PosLayout';
import { PlatformOwnerConsole } from '../../src/components/owner/PlatformOwnerConsole';
import { SignInScreen } from '../../src/components/auth/SignInScreen';
import { OperationalEntryScreen } from '../../src/components/auth/OperationalEntryScreen';
import { PasswordSetupScreen, OwnerMfaScreen } from '../../src/components/auth/FirstAccessSecurity';
import KdsShell from '../../src/shells/KdsShell';
import TablesShell from '../../src/shells/TablesShell';
const screen = new URLSearchParams(location.search).get('screen');
const screens = { owner: <PlatformOwnerConsole me={{ user: { full_name: 'Owner de teste', email: 'owner@example.test' } }}/>, manage: <ManagementLayout />, pos: <PosLayout />, operate: <OperationalEntryScreen />, login: <SignInScreen />, password: <PasswordSetupScreen onComplete={async () => { }}/>, mfa: <OwnerMfaScreen onComplete={async () => { }}/>, kds: <KdsShell />, tables: <TablesShell /> };
class Boundary extends React.Component {
    state = { error: null };
    static getDerivedStateFromError(error) { return { error: String(error) }; }
    ;
    render() { return this.state.error ? <pre data-error>{this.state.error}</pre> : this.props.children; }
}
createRoot(document.getElementById('root')).render(<Boundary><PosProvider>{screens[screen] || screens.manage}</PosProvider></Boundary>);
