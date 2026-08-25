// SPDX-License-Identifier: GPL-3.0-or-later

#include "ApiKeysPage.h"

#include <QFormLayout>
#include <QFont>
#include <QLabel>
#include <QLineEdit>
#include <QVBoxLayout>

namespace
{
void
hardenSecretField( QLineEdit* field, const QString& objectName, const QString& accessibleName )
{
    field->setObjectName( objectName );
    field->setAccessibleName( accessibleName );
    field->setAccessibleDescription( QObject::tr( "Optional private API credential" ) );
    field->setEchoMode( QLineEdit::Password );
    field->setInputMethodHints( Qt::ImhHiddenText | Qt::ImhSensitiveData | Qt::ImhNoPredictiveText
                                | Qt::ImhNoAutoUppercase );
    field->setDragEnabled( false );
    field->setClearButtonEnabled( false );
    field->setMaxLength( 4096 );
    field->setPlaceholderText( QObject::tr( "Optional" ) );
}

void
bestEffortClear( QLineEdit* field )
{
    const int length = field->text().size();
    if ( length > 0 )
    {
        field->setText( QString( length, QChar( 0 ) ) );
    }
    field->clear();
}
}  // namespace

ApiKeysPage::ApiKeysPage( QWidget* parent )
    : QWidget( parent )
    , m_openRouterKey( new QLineEdit( this ) )
    , m_groqKey( new QLineEdit( this ) )
{
    auto* layout = new QVBoxLayout( this );
    layout->setSpacing( 18 );

    auto* title = new QLabel( tr( "Connect the DarkOS assistant" ), this );
    QFont titleFont = title->font();
    titleFont.setPointSize( titleFont.pointSize() + 6 );
    titleFont.setBold( true );
    title->setFont( titleFont );
    title->setObjectName( QStringLiteral( "darkosApiKeysTitle" ) );
    layout->addWidget( title );

    auto* introduction = new QLabel(
        tr( "Add your own OpenRouter and Groq API keys for cloud chat and speech. "
            "Both fields are optional; DarkOS can still use configured local models or run without cloud AI." ),
        this );
    introduction->setWordWrap( true );
    introduction->setObjectName( QStringLiteral( "darkosApiKeysIntroduction" ) );
    layout->addWidget( introduction );

    hardenSecretField( m_openRouterKey,
                       QStringLiteral( "darkosOpenRouterApiKey" ),
                       tr( "OpenRouter API key" ) );
    hardenSecretField( m_groqKey, QStringLiteral( "darkosGroqApiKey" ), tr( "Groq API key" ) );

    auto* form = new QFormLayout;
    form->setFieldGrowthPolicy( QFormLayout::ExpandingFieldsGrow );
    auto* openRouterLabel = new QLabel( tr( "OpenRouter API key:" ), this );
    openRouterLabel->setBuddy( m_openRouterKey );
    auto* groqLabel = new QLabel( tr( "Groq API key:" ), this );
    groqLabel->setBuddy( m_groqKey );
    form->addRow( openRouterLabel, m_openRouterKey );
    form->addRow( groqLabel, m_groqKey );
    layout->addLayout( form );

    auto* privacy = new QLabel(
        tr( "Keys are stored only for the installed user in ~/.config/darkos/env. "
            "The file is private (mode 0600), and the values are never written to the installer log." ),
        this );
    privacy->setWordWrap( true );
    privacy->setObjectName( QStringLiteral( "darkosApiKeysPrivacyNotice" ) );
    layout->addWidget( privacy );
    layout->addStretch();
}

ApiKeysPage::~ApiKeysPage()
{
    clearSecrets();
}

QString
ApiKeysPage::openRouterKey() const
{
    return m_openRouterKey->text();
}

QString
ApiKeysPage::groqKey() const
{
    return m_groqKey->text();
}

bool
ApiKeysPage::hasAnyKey() const
{
    return !m_openRouterKey->text().isEmpty() || !m_groqKey->text().isEmpty();
}

void
ApiKeysPage::clearSecrets()
{
    bestEffortClear( m_openRouterKey );
    bestEffortClear( m_groqKey );
}
