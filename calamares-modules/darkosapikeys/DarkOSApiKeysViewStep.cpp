// SPDX-License-Identifier: GPL-3.0-or-later

#include "DarkOSApiKeysViewStep.h"

#include "ApiKeysPage.h"
#include "WriteApiKeysJob.h"

#include <utility>

CALAMARES_PLUGIN_FACTORY_DEFINITION( DarkOSApiKeysViewStepFactory,
                                    registerPlugin< DarkOSApiKeysViewStep >(); )

DarkOSApiKeysViewStep::DarkOSApiKeysViewStep( QObject* parent )
    : Calamares::ViewStep( parent )
    , m_widget( new ApiKeysPage )
{
}

DarkOSApiKeysViewStep::~DarkOSApiKeysViewStep()
{
    if ( m_widget && m_widget->parent() == nullptr )
    {
        m_widget->deleteLater();
    }
}

QString
DarkOSApiKeysViewStep::prettyName() const
{
    return tr( "AI services", "@title" );
}

QString
DarkOSApiKeysViewStep::prettyStatus() const
{
    return m_widget->hasAnyKey() ? tr( "Private API credentials will be stored for the installed user." )
                                 : tr( "No cloud API credentials will be stored." );
}

QWidget*
DarkOSApiKeysViewStep::widget()
{
    return m_widget;
}

bool
DarkOSApiKeysViewStep::isNextEnabled() const
{
    return true;
}

bool
DarkOSApiKeysViewStep::isBackEnabled() const
{
    return true;
}

bool
DarkOSApiKeysViewStep::isAtBeginning() const
{
    return true;
}

bool
DarkOSApiKeysViewStep::isAtEnd() const
{
    return true;
}

Calamares::JobList
DarkOSApiKeysViewStep::jobs() const
{
    if ( !m_widget->hasAnyKey() )
    {
        return Calamares::JobList();
    }

    QString openRouterKey = m_widget->openRouterKey();
    QString groqKey = m_widget->groqKey();
    Calamares::JobList jobs;
    jobs.append(
        Calamares::job_ptr( new WriteApiKeysJob( std::move( openRouterKey ), std::move( groqKey ) ) ) );
    m_widget->clearSecrets();
    return jobs;
}

void
DarkOSApiKeysViewStep::onCancel()
{
    m_widget->clearSecrets();
}
